"""Background YOLO inference and lower-controller communication worker.

所有耗时工作（读视频帧、YOLO 推理、TCP/串口收发）都在这个 ``QThread`` 里完成，
Qt 主线程只负责把 ``QImage`` 贴到界面上，因此窗口在推理时不会卡死。
"""

import threading
import time
from typing import Optional

import cv2
from PyQt5 import QtCore, QtGui

from .controller import SortingController
from .detectors import Detection, YoloDetector
from .frame_sources import FrameSource, create_frame_source
from .protocol import WASTE_NAMES, WasteType
from .transport import SerialTransport, TcpTransport


BOX_COLORS = {
    WasteType.RECYCLABLE: (255, 150, 30),
    WasteType.KITCHEN: (60, 190, 70),
    WasteType.HAZARDOUS: (40, 40, 230),
    WasteType.OTHER: (160, 160, 160),
}
DRAW_WASTE_NAMES = {
    WasteType.RECYCLABLE: "recyclable",
    WasteType.KITCHEN: "kitchen",
    WasteType.HAZARDOUS: "hazardous",
    WasteType.OTHER: "other",
}


class SortingWorker(QtCore.QThread):
    frame_ready = QtCore.pyqtSignal(QtGui.QImage)
    state_changed = QtCore.pyqtSignal(str)
    counts_changed = QtCore.pyqtSignal(object)
    bins_changed = QtCore.pyqtSignal(object)
    detection_changed = QtCore.pyqtSignal(object)
    model_changed = QtCore.pyqtSignal(str)
    source_changed = QtCore.pyqtSignal(str)
    source_finished = QtCore.pyqtSignal()
    log_message = QtCore.pyqtSignal(str)
    connection_changed = QtCore.pyqtSignal(bool)
    fps_changed = QtCore.pyqtSignal(float)
    # (当前帧下标, 总帧数, 源帧率)：视频进度条与时间标签使用，摄像头时总帧数为 0。
    progress_changed = QtCore.pyqtSignal(int, int, float)
    # 输入源的类型、分辨率、帧率等说明文字
    source_info = QtCore.pyqtSignal(str)
    # 下位机连接方式（TCP 地址 / 串口设备）
    connection_info = QtCore.pyqtSignal(str)
    # 累计发出的帧数、收到的帧数
    traffic_changed = QtCore.pyqtSignal(int, int)

    def __init__(
        self,
        sim_host: str,
        sim_port: int,
        source_kind: str = "video",
        source_value: str = "assets/assessment_demo.mp4",
        weights: str = "Predict/best.pt",
        confidence: float = 0.50,
        transport_kind: str = "tcp",
        serial_port: str = "/dev/ttyUSB0",
        baudrate: int = 9600,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.sim_host = sim_host
        self.sim_port = sim_port
        self.source_kind = source_kind
        self.source_value = source_value
        self.weights = weights
        self.confidence = confidence
        self.transport_kind = transport_kind
        self.serial_port = serial_port
        self.baudrate = baudrate
        self._stop_event = threading.Event()
        self._running_event = threading.Event()
        self._settings_lock = threading.Lock()
        self._reset_requested = False
        self._restart_requested = False
        self._source_change = None
        self._seek_request = None  # type: Optional[int]
        self._controller = None  # type: Optional[SortingController]
        self._source = None  # type: Optional[FrameSource]
        self._detector = None  # type: Optional[YoloDetector]
        self._at_video_end = False
        self._tx_count = 0
        self._rx_count = 0
        self._last_camera_error = 0.0
        self._connecting = False
        self._connect_lock = threading.Lock()

    # ------------------------------------------------------------ 连接管理
    def _connect_in_background(self, transport, connection_name: str) -> None:
        """在独立线程里连接下位机。

        Windows 上向一个不存在的端口发起 TCP 连接会一直等到超时（可达 2 秒），
        如果放在主循环里同步调用，读帧和界面操作都会被拖慢，表现为“点了没反应”。
        因此连接尝试放到后台线程，主循环只负责检查 ``transport.connected``。
        """
        with self._connect_lock:
            if self._connecting:
                return
            self._connecting = True

        def runner() -> None:
            try:
                transport.connect()
                if self._stop_event.is_set():
                    transport.close()
                    return
                self.log_message.emit("{}连接成功".format(connection_name))
            except Exception as exc:  # 连接失败是常态，继续等下一次
                self.log_message.emit("等待{}：{}".format(connection_name, exc))
            finally:
                with self._connect_lock:
                    self._connecting = False

        threading.Thread(target=runner, name="lower-connect", daemon=True).start()

    # ------------------------------------------------------------ 外部控制
    def prepare_model(self) -> None:
        """Load PyTorch/YOLO before QThread starts.

        On Windows, importing PyTorch for the first time inside a newly-created
        QThread can stall Qt window creation.  Loading once on the GUI thread is
        deterministic; all subsequent inference still runs in this worker.
        """
        if self._detector is not None:
            return
        self.model_changed.emit("正在加载 {} …".format(self.weights))
        self._detector = YoloDetector(
            weights=self.weights,
            confidence=self.confidence,
        )
        self.model_changed.emit("已加载 · {}".format(self._detector.device))

    def start_processing(self) -> None:
        with self._settings_lock:
            if self._at_video_end:
                self._restart_requested = True
        self._running_event.set()

    def pause_processing(self) -> None:
        self._running_event.clear()
        self.state_changed.emit("已暂停")

    def request_reset(self) -> None:
        with self._settings_lock:
            self._reset_requested = True

    def request_source(self, kind: str, value: str = "") -> None:
        with self._settings_lock:
            self._source_change = (kind, value)
            self._seek_request = None
            self._restart_requested = False

    def request_seek(self, frame_index: int) -> None:
        """请求跳到指定帧（只在视频源时生效）。"""
        with self._settings_lock:
            self._seek_request = int(frame_index)

    def request_replay(self) -> None:
        """请求从第 0 帧重新播放。"""
        with self._settings_lock:
            self._restart_requested = True
        self._running_event.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._running_event.set()

    # ------------------------------------------------------------ 事件桥接
    def _event(self, name: str, data: dict) -> None:
        if name == "state":
            self.state_changed.emit(data["value"])
        elif name == "counts":
            self.counts_changed.emit(data["values"])
        elif name == "bins":
            self.bins_changed.emit(data["values"])
        elif name == "log":
            self.log_message.emit(data["message"])
        elif name in ("tx", "rx"):
            if name == "tx":
                self._tx_count += 1
            else:
                self._rx_count += 1
            self.traffic_changed.emit(self._tx_count, self._rx_count)
            self.log_message.emit("{}  {}".format(name.upper(), data["packet"]))

    def _describe_source(self) -> str:
        source = self._source
        if source is None:
            return ""
        if getattr(source, "kind", "") == "camera":
            return "实时流 · {}×{} · {:.0f} fps".format(
                getattr(source, "width", 0),
                getattr(source, "height", 0),
                getattr(source, "source_fps", 30.0),
            )
        return "视频文件 · {}×{} · {:.0f} fps · {} 帧".format(
            getattr(source, "frame_width", 0),
            getattr(source, "frame_height", 0),
            getattr(source, "source_fps", 0.0),
            getattr(source, "frame_count", 0),
        )

    def _emit_progress(self) -> None:
        source = self._source
        if source is None:
            return
        total = int(getattr(source, "frame_count", 0) or 0)
        current = int(getattr(source, "current_frame", 0) or 0)
        fps = float(getattr(source, "source_fps", 0.0) or 0.0)
        if getattr(source, "kind", "") == "video":
            self.progress_changed.emit(current, total, fps)

    def _apply_requests(self) -> None:
        with self._settings_lock:
            reset_requested = self._reset_requested
            self._reset_requested = False
            restart_requested = self._restart_requested
            self._restart_requested = False
            source_change = self._source_change
            self._source_change = None
            seek_request = self._seek_request
            self._seek_request = None

        if reset_requested and self._controller is not None:
            self._controller.reset()

        if source_change is not None:
            try:
                new_source = create_frame_source(*source_change)
            except Exception as exc:
                self.log_message.emit("切换图像源失败：{}".format(exc))
                self.state_changed.emit("输入源不可用")
            else:
                old_source, self._source = self._source, new_source
                if old_source is not None:
                    old_source.release()
                self._at_video_end = False
                if self._controller is not None:
                    # 新输入源代表新场景，清掉旧的稳定帧计数与冷却状态。
                    self._controller.resume()
                self.source_changed.emit(new_source.display_name)
                self.source_info.emit(self._describe_source())
                self.detection_changed.emit(None)
                self.progress_changed.emit(
                    0,
                    int(getattr(new_source, "frame_count", 0) or 0),
                    float(getattr(new_source, "source_fps", 0.0) or 0.0),
                )
                self.log_message.emit("图像源已切换：{}".format(new_source.display_name))

        if seek_request is not None and self._source is not None:
            seek = getattr(self._source, "seek_frame", None)
            if callable(seek):
                if seek(seek_request):
                    self._at_video_end = False
                    if self._controller is not None:
                        self._controller.resume()
                    self.log_message.emit("已跳转到第 {} 帧".format(seek_request))
                    self._emit_progress()
                else:
                    self.log_message.emit("跳转失败：第 {} 帧超出视频范围".format(seek_request))
            else:
                self.log_message.emit("当前输入源不支持跳转（摄像头）")

        if restart_requested and self._source is not None:
            if self._source.restart():
                self._at_video_end = False
                if self._controller is not None:
                    self._controller.resume()
                self.log_message.emit("视频已从头开始")
                self._emit_progress()
            else:
                self.log_message.emit("当前输入源不支持重新播放")

    # ------------------------------------------------------------ 绘制
    @staticmethod
    def _to_qimage(frame) -> QtGui.QImage:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        return QtGui.QImage(
            rgb.data, width, height, channels * width, QtGui.QImage.Format_RGB888
        ).copy()

    @staticmethod
    def _draw_detections(frame, detections) -> None:
        for detection in detections:
            x1, y1, x2, y2 = detection.box
            color = BOX_COLORS[detection.waste_type]
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
            label = "{} / {} {:.0f}%".format(
                detection.class_name,
                DRAW_WASTE_NAMES[detection.waste_type],
                detection.confidence * 100,
            )
            cv2.putText(
                frame,
                label,
                (x1, max(26, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.68,
                color,
                2,
                cv2.LINE_AA,
            )

    # ------------------------------------------------------------ 主循环
    def run(self) -> None:
        if self.transport_kind == "serial":
            transport = SerialTransport(self.serial_port, self.baudrate)
            connection_name = "串口 {} @ {}".format(self.serial_port, self.baudrate)
        else:
            transport = TcpTransport(self.sim_host, self.sim_port)
            connection_name = "模拟下位机 {}:{}".format(self.sim_host, self.sim_port)

        self._controller = SortingController(transport, self._event)
        last_connect_attempt = 0.0
        frame_times = []
        previous_connection = False
        last_camera_error = 0.0

        self.connection_info.emit(
            "串口 {} @ {} bps".format(self.serial_port, self.baudrate)
            if self.transport_kind == "serial"
            else "TCP {}:{}".format(self.sim_host, self.sim_port)
        )

        try:
            if self._detector is None:
                self.prepare_model()
            detector = self._detector
            self.model_changed.emit("已加载 · {}".format(detector.device))
            self.log_message.emit("YOLO 权重加载成功：{} ({})".format(self.weights, detector.device))

            self._source = create_frame_source(self.source_kind, self.source_value)
            self.source_changed.emit(self._source.display_name)
            self.source_info.emit(self._describe_source())
            self.log_message.emit("图像源已打开：{}".format(self._source.display_name))
            self._emit_progress()

            while not self._stop_event.is_set():
                now = time.monotonic()
                if (
                    not transport.connected
                    and not self._connecting
                    and now - last_connect_attempt >= 2.0
                ):
                    last_connect_attempt = now
                    self._connect_in_background(transport, connection_name)

                if transport.connected != previous_connection:
                    previous_connection = transport.connected
                    self.connection_changed.emit(previous_connection)
                    if previous_connection:
                        self.log_message.emit("下位机已连通，状态机回到等待识别")
                        if self._controller is not None:
                            self._controller.resume()
                    else:
                        self.log_message.emit("下位机连接断开，正在自动重连…")

                self._apply_requests()
                self._controller.poll()

                if not self._running_event.is_set():
                    self.msleep(40)
                    continue

                ok, frame = self._source.read() if self._source is not None else (False, None)
                if not ok or frame is None:
                    if self._source is not None and getattr(self._source, "kind", "") == "video":
                        self._at_video_end = True
                        self._running_event.clear()
                        self.detection_changed.emit(None)
                        self._emit_progress()
                        self.source_finished.emit()
                        total = int(getattr(self._source, "frame_count", 0) or 0)
                        if getattr(self._source, "decode_error", False):
                            self.state_changed.emit("视频解码失败")
                            self.log_message.emit(
                                "视频在第 {} 帧解码失败，请检查文件格式".format(
                                    getattr(self._source, "current_frame", 0)
                                )
                            )
                        else:
                            self.state_changed.emit("视频播放完成")
                            self.log_message.emit(
                                "视频播放完成（共 {} 帧），再次点击“开始/重新播放”可从头播放".format(total)
                            )
                    else:
                        # 摄像头偶发取帧失败不必刷屏，最多每 2 秒提示一次。
                        if now - last_camera_error >= 2.0:
                            last_camera_error = now
                            detail = getattr(self._source, "last_error", "") if self._source else ""
                            if detail:
                                self.state_changed.emit("摄像头不可用")
                                self.log_message.emit(detail)
                            else:
                                self.log_message.emit(
                                    "摄像头暂时取不到画面，正在自动重连…（检查是否被其他程序占用）"
                                )
                        self.msleep(120)
                    continue

                started = time.monotonic()
                detections = detector.detect(frame)
                best = detections[0] if detections else None
                self.detection_changed.emit(best)

                # Communication is not faked: only a connected lower controller
                # receives stable YOLO results and confirms completed actions.
                if transport.connected:
                    self._controller.process_detection(best)

                self._draw_detections(frame, detections)
                self.frame_ready.emit(self._to_qimage(frame))
                if getattr(self._source, "kind", "") == "video":
                    self._emit_progress()

                completed = time.monotonic()
                frame_times.append(completed)
                frame_times = [stamp for stamp in frame_times if completed - stamp <= 1.0]
                self.fps_changed.emit(float(len(frame_times)))

                source_fps = self._source.source_fps if self._source is not None else 0.0
                target_delay = 1.0 / source_fps if source_fps > 1.0 else 0.03
                remaining = target_delay - (completed - started)
                if remaining > 0:
                    self.msleep(int(remaining * 1000))
        except Exception as exc:
            self.model_changed.emit("加载或运行失败")
            self.log_message.emit("工作线程异常：{}".format(exc))
            self.state_changed.emit("运行异常")
        finally:
            if self._source is not None:
                self._source.release()
            transport.close()
            self.connection_changed.emit(False)
