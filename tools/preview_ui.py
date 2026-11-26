"""界面预览工具（不需要模型、不需要下位机）。

用途：
1. 开发时快速检查布局、配色和缩放效果；
2. 保存界面截图，便于写 README / PPT。

    python -m tools.preview_ui out/ui.png
"""

import argparse
import sys
from pathlib import Path

import cv2
from PyQt5 import QtCore, QtGui, QtWidgets

from app.ui import MainWindow


class StubWorker(QtCore.QObject):
    """只提供信号和空方法的替身，用来在不加载 YOLO 的情况下渲染界面。"""

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
    progress_changed = QtCore.pyqtSignal(int, int, float)
    source_info = QtCore.pyqtSignal(str)
    connection_info = QtCore.pyqtSignal(str)
    traffic_changed = QtCore.pyqtSignal(int, int)

    def prepare_model(self):
        return None

    def start(self):
        return None

    def start_processing(self):
        return None

    def pause_processing(self):
        return None

    def request_reset(self):
        return None

    def request_source(self, kind, value=""):
        return None

    def request_seek(self, frame_index):
        return None

    def request_replay(self):
        return None

    def stop(self):
        return None

    def wait(self, timeout=0):
        return True


def _sample_frame() -> QtGui.QImage:
    capture = cv2.VideoCapture("assets/assessment_demo.mp4")
    ok, frame = capture.read()
    capture.release()
    if not ok:
        frame = None
    if frame is None:
        import numpy as np

        frame = np.full((720, 1280, 3), 24, dtype=np.uint8)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    height, width, channels = rgb.shape
    return QtGui.QImage(
        rgb.data, width, height, channels * width, QtGui.QImage.Format_RGB888
    ).copy()


def populate(window: MainWindow) -> None:
    from app.protocol import WASTE_NAMES, WasteType

    window.model_label.setText("已加载 · cpu")
    window.source_label.setText("assets/assessment_demo.mp4")
    window._on_source_info("视频文件 · 1280×720 · 25 fps · 396 帧")
    window._on_connection_info("TCP lower-sim:9000")
    window._on_traffic(42, 42)
    window._on_state_changed("下位机执行中")
    window.update_connection(True)
    window.update_fps(11)
    window.camera_label.set_frame(_sample_frame())
    window.update_progress(247, 396, 25.0)
    window.class_label.setText("battery")
    window.waste_label.setText(WASTE_NAMES[WasteType.HAZARDOUS])
    window.waste_label.setStyleSheet("color: #F87171;")
    window.confidence_label.setText("90.5%")
    window.confidence_bar.setValue(91)
    window.box_label.setText("402 × 331 px")
    window.update_counts(
        {
            WASTE_NAMES[WasteType.RECYCLABLE]: 2,
            WASTE_NAMES[WasteType.KITCHEN]: 1,
            WASTE_NAMES[WasteType.HAZARDOUS]: 1,
            WASTE_NAMES[WasteType.OTHER]: 0,
        }
    )
    window.update_bins(
        {
            WASTE_NAMES[WasteType.RECYCLABLE]: False,
            WASTE_NAMES[WasteType.KITCHEN]: False,
            WASTE_NAMES[WasteType.HAZARDOUS]: False,
            WASTE_NAMES[WasteType.OTHER]: True,
        }
    )
    window.start_button.setText("暂停识别")
    window.start_button.setEnabled(True)
    window.source_button.setEnabled(True)
    window.replay_button.setEnabled(True)
    window.append_log("YOLO 权重加载成功：Predict/best.pt (cpu)")
    window.append_log("图像源已打开：assets/assessment_demo.mp4")
    window.append_log("下位机已连通，状态机回到等待识别")
    window.append_log("识别稳定：有害垃圾（序号 4）→ 已发送 WASTE_RESULT")
    window.append_log("TX  AA 55 03 01 04 01 09")
    window.append_log("RX  AA 55 03 02 01 04 0A")
    window.append_log("收到 ACK（序号 4），等待 ACTION_DONE")
    window.append_log("RX  AA 55 02 03 04 09")
    window.append_log("WASTE_RESULT → ACK → ACTION_DONE 完成：有害垃圾，本类累计 1，总计 4")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="渲染主界面并保存截图")
    parser.add_argument("output", nargs="?", default="out/ui_preview.png")
    parser.add_argument("--width", type=int, default=1360)
    parser.add_argument("--height", type=int, default=860)
    parser.add_argument("--no-show", action="store_true", help="不显示窗口，只截图")
    args = parser.parse_args(argv)

    app = QtWidgets.QApplication(sys.argv[:1])
    worker = StubWorker()
    window = MainWindow(worker)
    window.resize(args.width, args.height)
    populate(window)
    if not args.no_show:
        window.show()
    app.processEvents()
    app.processEvents()

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    pixmap = window.grab()
    saved = pixmap.save(args.output)
    print("screenshot saved: {} ({})".format(args.output, "ok" if saved else "failed"))
    return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())

