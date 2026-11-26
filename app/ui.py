"""PyQt5 主界面：分拣控制台（浅色主题、原生窗口）。

界面只做三件事：把画面显示清楚、把状态说明白、把操作交给后台线程。
所有耗时动作（读帧、推理、通信、打开摄像头/视频）都在 :class:`SortingWorker`
里执行，通过信号回到主线程，所以窗口始终可拖动、可缩放、可退出。

布局（左“看”右“读”，操作集中在底部）：

    ┌──────────────────────────────────────────┬─────────────────────┐
    │ 识别画面（检测框 + 输入源徽标）           │ 当前识别结果         │
    │ 进度条 / 时间 / 帧号 / 分辨率             │ 分拣统计（比例条）   │
    ├──────────────────────────────────────────┤ 通信（TX/RX 计数）   │
    │ 分拣流程 ①识别稳定 ②下发 ③确认 ④计数      │ 通信日志             │
    └──────────────────────────────────────────┴─────────────────────┘

输入源只有一个入口：底部“导入 / 摄像头”按钮打开同一个对话框，
在“本地视频 / 摄像头”两个页签之间切换即可，不用分两次操作。
"""

import datetime
from html import escape as html_escape
from pathlib import Path
from typing import Dict, List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from .detectors import Detection
from .frame_sources import (
    VIDEO_SUFFIXES,
    CameraInfo,
    probe_cameras,
    probe_video,
)
from .protocol import WASTE_NAMES, WasteType
from .theme import QSS, STATE_COLORS, WASTE_COLORS
from .worker import SortingWorker


WASTE_ORDER = (WasteType.RECYCLABLE, WasteType.KITCHEN, WasteType.HAZARDOUS, WasteType.OTHER)

# 状态 → 分拣流程第几步（-1 表示不在流程中）
_PIPELINE_STEP = {
    "等待识别": 0,
    "等待下位机确认": 1,
    "下位机执行中": 2,
    "等待物体离开": 3,
    "压缩中": 3,
    "已暂停": -1,
    "视频播放完成": -1,
}
_ERROR_STATES = ("通信异常", "运行异常", "视频解码失败", "输入源不可用", "摄像头不可用")


def _format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    return "{:02d}:{:02d}".format(total // 60, total % 60)


class VideoView(QtWidgets.QLabel):
    """等比缩放显示 BGR 帧；窗口缩放时重新采样而不是拉伸变形。"""

    def __init__(self, placeholder: str, parent=None) -> None:
        super().__init__(parent)
        self._pixmap = None  # type: Optional[QtGui.QPixmap]
        self._placeholder = placeholder
        self.setObjectName("VideoView")
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumSize(480, 270)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.setText(placeholder)

    def set_frame(self, image: QtGui.QImage) -> None:
        self._pixmap = QtGui.QPixmap.fromImage(image)
        self._refresh()

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text
        if self._pixmap is None:
            self.setText(text)

    def clear_frame(self) -> None:
        self._pixmap = None
        self.clear()
        self.setText(self._placeholder)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        if self._pixmap is None:
            return
        self.setPixmap(
            self._pixmap.scaled(
                self.size(),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
        )


class LogView(QtWidgets.QPlainTextEdit):
    """日志视图：sizeHint 给小一点，让它在卡片里按剩余空间伸展，而不是把面板撑出滚动条。"""

    def sizeHint(self) -> QtCore.QSize:
        hint = super().sizeHint()
        hint.setHeight(128)
        return hint


class PipelineWidget(QtWidgets.QFrame):
    """把状态机画成四步流水线，让人一眼看出“现在卡在哪”。"""

    STEPS = ("识别稳定", "下发指令", "下位机确认", "计数 +1")
    _STYLE = {
        "idle": "color:#94A3B8; background:#F1F5F9; border:1px solid #E2E8F0;",
        "active": "color:#FFFFFF; background:#2563EB; border:1px solid #1D4ED8;",
        "done": "color:#FFFFFF; background:#16A34A; border:1px solid #15803D;",
        "error": "color:#FFFFFF; background:#DC2626; border:1px solid #B91C1C;",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(6)

        title = QtWidgets.QLabel("分拣流程")
        title.setObjectName("CardTitle")
        row.addWidget(title)
        row.addSpacing(6)

        self.steps = []  # type: List[QtWidgets.QLabel]
        for index, name in enumerate(self.STEPS):
            if index:
                arrow = QtWidgets.QLabel("→")
                arrow.setStyleSheet("color:#CBD5E1; font-size:14px;")
                row.addWidget(arrow)
            label = QtWidgets.QLabel("{}  {}".format(index + 1, name))
            label.setAlignment(QtCore.Qt.AlignCenter)
            label.setMinimumHeight(30)
            row.addWidget(label)
            self.steps.append(label)

        row.addStretch(1)
        self.caption = QtWidgets.QLabel("等待启动")
        self.caption.setStyleSheet("color:#94A3B8; font-size:12px; font-weight:600;")
        row.addWidget(self.caption)
        self.set_state("")

    def set_state(self, text: str) -> None:
        if text:
            self.caption.setText(text)
            self.caption.setStyleSheet(
                "color:{}; font-size:12px; font-weight:600;".format(
                    STATE_COLORS.get(text, "#64748B")
                )
            )

        if text in _ERROR_STATES:
            for label in self.steps:
                self._paint(label, "error")
            return

        step = _PIPELINE_STEP.get(text, -1)
        for index, label in enumerate(self.steps):
            if step < 0:
                self._paint(label, "idle")
            elif index < step:
                self._paint(label, "done")
            elif index == step:
                self._paint(label, "active")
            else:
                self._paint(label, "idle")

    def _paint(self, label: QtWidgets.QLabel, mode: str) -> None:
        label.setStyleSheet(
            self._STYLE[mode] + "border-radius:9px; padding:6px 13px; font-size:12px; font-weight:600;"
        )


class _CameraProbeThread(QtCore.QThread):
    """在后台枚举摄像头，避免打开设备时卡住界面。"""

    found = QtCore.pyqtSignal(object)

    def run(self) -> None:  # noqa: D401 - Qt 线程入口
        try:
            cameras = probe_cameras(max_index=3)
        except Exception:
            cameras = []
        self.found.emit(cameras)


class SourceDialog(QtWidgets.QDialog):
    """一个窗口里选择输入源：本地视频 / 摄像头。

    结果放在 ``kind``（video / camera）与 ``value``（文件路径 / 设备编号）。
    """

    def __init__(self, parent=None, initial: str = "video", last_dir: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("选择输入源")
        self.setMinimumWidth(560)
        self.kind = "video"
        self.value = ""
        self._cameras = []  # type: List[CameraInfo]
        self._video_info = None
        self._probe = None  # type: Optional[_CameraProbeThread]
        self._last_dir = last_dir

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("导入视频 或 打开摄像头")
        title.setStyleSheet("font-size:17px; font-weight:700; color:#0B1220;")
        caption = QtWidgets.QLabel("两种输入源都在这个窗口里选择，确定后立即开始识别。")
        caption.setStyleSheet("color:#64748B; font-size:12px;")
        layout.addWidget(title)
        layout.addWidget(caption)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_video_tab(), "本地视频")
        self.tabs.addTab(self._build_camera_tab(), "摄像头")
        layout.addWidget(self.tabs, 1)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        cancel = QtWidgets.QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.open_button = QtWidgets.QPushButton("开始识别")
        self.open_button.setObjectName("PrimaryButton")
        self.open_button.clicked.connect(self._accept_current)
        buttons.addWidget(self.open_button)
        layout.addLayout(buttons)

        self.tabs.setCurrentIndex(0 if initial != "camera" else 1)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed(self.tabs.currentIndex())

    # ------------------------------------------------------------------ 构建
    def _build_video_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        self.path_edit = QtWidgets.QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("尚未选择视频文件…")
        browse = QtWidgets.QPushButton("浏览文件…")
        browse.clicked.connect(self._browse_video)
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        self.video_info = QtWidgets.QLabel("支持 mp4 / avi / mov / mkv / wmv 等格式，逐帧送进 YOLO")
        self.video_info.setStyleSheet("color:#64748B; font-size:12px;")
        self.video_info.setWordWrap(True)
        layout.addWidget(self.video_info)

        hint = QtWidgets.QLabel("提示：也可以把视频文件直接拖进主窗口。")
        hint.setStyleSheet("color:#94A3B8; font-size:11px;")
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_camera_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.camera_status = QtWidgets.QLabel("正在检测摄像头…")
        self.camera_status.setStyleSheet("color:#64748B; font-size:12px;")
        layout.addWidget(self.camera_status)

        self.camera_list = QtWidgets.QListWidget()
        self.camera_list.setMinimumHeight(128)
        self.camera_list.itemDoubleClicked.connect(lambda _item: self._accept_current())
        layout.addWidget(self.camera_list)

        manual = QtWidgets.QHBoxLayout()
        manual.setSpacing(8)
        label = QtWidgets.QLabel("手动编号")
        label.setStyleSheet("color:#94A3B8; font-size:12px;")
        self.spin = QtWidgets.QSpinBox()
        self.spin.setRange(0, 9)
        self.spin.setFixedWidth(66)
        self.manual_button = QtWidgets.QPushButton("打开该编号")
        self.manual_button.setObjectName("SmallButton")
        self.manual_button.clicked.connect(self._accept_camera_index)
        self.refresh_button = QtWidgets.QPushButton("重新检测")
        self.refresh_button.setObjectName("SmallButton")
        self.refresh_button.clicked.connect(self._start_probe)
        manual.addWidget(label)
        manual.addWidget(self.spin)
        manual.addWidget(self.manual_button)
        manual.addStretch(1)
        manual.addWidget(self.refresh_button)
        layout.addLayout(manual)
        return page

    # ------------------------------------------------------------------ 视频
    def _browse_video(self) -> None:
        start_dir = self._last_dir or (
            str(Path("assets").resolve()) if Path("assets").is_dir() else str(Path.cwd())
        )
        path, _selected = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "选择视频文件",
            start_dir,
            "视频文件 (*.mp4 *.avi *.mov *.mkv *.wmv *.flv);;所有文件 (*)",
            options=QtWidgets.QFileDialog.DontUseNativeDialog,
        )
        if path:
            self._set_video(path)

    def _set_video(self, path: str) -> None:
        self.path_edit.setText(path)
        suffix = Path(path).suffix.lower()
        if suffix and suffix not in VIDEO_SUFFIXES:
            self.video_info.setText("不支持的扩展名 {}，请选择视频文件".format(suffix))
            self.video_info.setStyleSheet("color:#DC2626; font-size:12px;")
            self._video_info = None
            self._update_open_button()
            return

        info = probe_video(path)
        if info is None:
            message = "无法读取该文件：可能不是视频，或已损坏 / 缺少解码器"
            if not Path(path).is_file():
                message = "文件不存在：{}".format(path)
            self.video_info.setText(message)
            self.video_info.setStyleSheet("color:#DC2626; font-size:12px;")
            self._video_info = None
        else:
            self._video_info = info
            self.video_info.setText("已选择：{}".format(info.label))
            self.video_info.setStyleSheet("color:#16A34A; font-size:12px;")
            self._last_dir = str(Path(path).parent)
        self._update_open_button()

    # ------------------------------------------------------------------ 摄像头
    def _start_probe(self) -> None:
        if self._probe is not None and self._probe.isRunning():
            return
        self._cameras = []
        self.camera_list.clear()
        self.refresh_button.setEnabled(False)
        self.camera_status.setText("正在检测摄像头…（约需 1~3 秒）")
        self._probe = _CameraProbeThread(self)
        self._probe.found.connect(self._on_cameras_found)
        self._probe.start()

    def _on_cameras_found(self, cameras) -> None:
        self._cameras = list(cameras)
        self.camera_list.clear()
        for camera in self._cameras:
            self.camera_list.addItem(camera.label)
        self.refresh_button.setEnabled(True)
        if self._cameras:
            self.camera_status.setText(
                "检测到 {} 个摄像头，选中后点击“开始识别”".format(len(self._cameras))
            )
            self.camera_list.setCurrentRow(0)
        else:
            self.camera_status.setText(
                "未检测到摄像头：可能被其他程序占用（微信 / QQ / 钉钉），请关闭后点“重新检测”"
            )
        self._update_open_button()

    # ------------------------------------------------------------------ 状态
    def _on_tab_changed(self, index: int) -> None:
        self.kind = "video" if index == 0 else "camera"
        if self.kind == "camera" and not self._cameras:
            self._start_probe()
        self._update_open_button()

    def _update_open_button(self) -> None:
        if self.kind == "video":
            enabled = self._video_info is not None
        else:
            enabled = True  # 摄像头可以用手动编号尝试
        self.open_button.setEnabled(enabled)

    def _accept_current(self) -> None:
        if self.kind == "video":
            if self._video_info is None:
                return
            self.value = self._video_info.path
            self.accept()
            return
        row = self.camera_list.currentRow()
        if 0 <= row < len(self._cameras):
            self.spin.setValue(self._cameras[row].index)
        self._accept_camera_index()

    def _accept_camera_index(self) -> None:
        self.kind = "camera"
        self.value = str(int(self.spin.value()))
        self.accept()

    # ------------------------------------------------------------------ 收尾
    def _stop_probe(self) -> None:
        if self._probe is not None and self._probe.isRunning():
            try:
                self._probe.found.disconnect()
            except TypeError:
                pass
            self._probe.wait(5000)
        self._probe = None

    def done(self, result: int) -> None:
        self._stop_probe()
        super().done(result)


class RootWidget(QtWidgets.QWidget):
    """根容器：接收“把视频拖进来”的拖放事件。"""

    def __init__(self, on_video_dropped, parent=None) -> None:
        super().__init__(parent)
        self._on_video = on_video_dropped
        self.setAcceptDrops(True)

    @staticmethod
    def _video_paths(event) -> List[str]:
        if not event.mimeData().hasUrls():
            return []
        paths = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local and Path(local).suffix.lower() in VIDEO_SUFFIXES:
                paths.append(local)
        return paths

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if self._video_paths(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if self._video_paths(event):
            event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        paths = self._video_paths(event)
        if paths:
            self._on_video(paths[0])
            event.acceptProposedAction()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, worker: SortingWorker, auto_start: bool = False) -> None:
        super().__init__()
        self.worker = worker
        self._processing = False
        self._slider_dragging = False
        self._total_frames = 0
        self._source_fps = 30.0
        self._source_ready_once = False
        self._is_camera = False
        self._last_video_dir = ""
        self.count_labels = {}  # type: Dict[str, QtWidgets.QLabel]
        self.count_bars = {}  # type: Dict[str, QtWidgets.QProgressBar]
        self.bin_labels = {}  # type: Dict[str, QtWidgets.QLabel]
        self._build_ui()
        self._connect_signals()
        self._auto_start = auto_start
        QtCore.QTimer.singleShot(50, self._initialize_worker)

    # ================================================================ 构建
    def _card(self, title: str, hint: str = "", right: QtWidgets.QWidget = None):
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        layout = QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(16, 11, 16, 11)
        layout.setSpacing(8)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("CardTitle")
        row.addWidget(title_label)
        if hint:
            hint_label = QtWidgets.QLabel(hint)
            hint_label.setObjectName("CardHint")
            row.addWidget(hint_label)
        row.addStretch(1)
        if right is not None:
            row.addWidget(right)
        layout.addLayout(row)
        card.content_layout = layout  # type: ignore[attr-defined]
        return card

    def _build_ui(self) -> None:
        self.setWindowTitle("智能垃圾分拣控制台")
        self.setMinimumSize(1100, 720)
        self.resize(1480, 920)
        self.setAcceptDrops(True)

        root_widget = RootWidget(self._on_video_dropped, self)
        root_widget.setObjectName("Root")
        self.setCentralWidget(root_widget)
        root = QtWidgets.QVBoxLayout(root_widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        body_host = QtWidgets.QWidget()
        body_layout = QtWidgets.QHBoxLayout(body_host)
        body_layout.setContentsMargins(16, 12, 16, 6)
        body_layout.setSpacing(0)
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self._build_left())
        self.splitter.addWidget(self._build_right())
        self.splitter.setStretchFactor(0, 5)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([920, 520])
        body_layout.addWidget(self.splitter)
        root.addWidget(body_host, 1)

        root.addWidget(self._build_footer())
        self.setStyleSheet(QSS)

    def _build_header(self) -> QtWidgets.QWidget:
        header = QtWidgets.QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(80)
        layout = QtWidgets.QHBoxLayout(header)
        layout.setContentsMargins(22, 12, 22, 12)
        layout.setSpacing(12)

        mark = QtWidgets.QFrame()
        mark.setObjectName("BrandMark")
        mark.setFixedSize(4, 36)
        layout.addWidget(mark)

        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(3)
        title = QtWidgets.QLabel("智能垃圾分拣控制台")
        title.setObjectName("Title")
        subtitle = QtWidgets.QLabel("视频 / 摄像头 → YOLO 识别 → 稳定帧判定 → 下位机确认 → 计数")
        subtitle.setObjectName("Subtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        layout.addLayout(titles)
        layout.addStretch(1)

        def chip(key: str, value: str) -> QtWidgets.QLabel:
            column = QtWidgets.QVBoxLayout()
            column.setSpacing(3)
            key_label = QtWidgets.QLabel(key)
            key_label.setObjectName("ChipKey")
            key_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            chip_label = QtWidgets.QLabel(value)
            chip_label.setObjectName("Chip")
            chip_label.setAlignment(QtCore.Qt.AlignCenter)
            chip_label.setMinimumWidth(112)
            column.addWidget(key_label)
            column.addWidget(chip_label)
            layout.addLayout(column)
            return chip_label

        self.state_label = chip("系统状态", "等待启动")
        self.connection_label = chip("下位机", "未连接")
        self.fps_label = chip("帧率", "0 FPS")
        self._paint_state("等待启动")
        self._paint_connection(False)
        return header

    def _build_left(self) -> QtWidgets.QWidget:
        left = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(left)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.source_badge = QtWidgets.QLabel("视频文件")
        self.source_badge.setObjectName("SourceBadge")
        card = self._card("识别画面", "每一帧都先送进 YOLO，再显示检测框", right=self.source_badge)
        card_layout = card.content_layout  # type: ignore[attr-defined]

        self.camera_label = VideoView("点击底部“导入 / 摄像头”，或把视频文件拖进窗口")
        card_layout.addWidget(self.camera_label, 1)

        progress_row = QtWidgets.QHBoxLayout()
        progress_row.setSpacing(10)
        self.position_label = QtWidgets.QLabel("00:00")
        self.position_label.setObjectName("MetaValue")
        self.position_label.setMinimumWidth(44)
        self.progress_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.setValue(0)
        self.progress_slider.setEnabled(False)
        self.progress_slider.setToolTip("拖动可跳转到视频任意位置（摄像头实时流不支持）")
        self.duration_label = QtWidgets.QLabel("00:00")
        self.duration_label.setObjectName("MetaValue")
        self.duration_label.setMinimumWidth(44)
        self.duration_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.frame_label = QtWidgets.QLabel("第 0 / 0 帧")
        self.frame_label.setObjectName("MetaKey")
        self.frame_label.setMinimumWidth(112)
        self.frame_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        progress_row.addWidget(self.position_label)
        progress_row.addWidget(self.progress_slider, 1)
        progress_row.addWidget(self.duration_label)
        progress_row.addWidget(self.frame_label)
        card_layout.addLayout(progress_row)

        meta_row = QtWidgets.QHBoxLayout()
        meta_row.setSpacing(6)
        source_key = QtWidgets.QLabel("输入源")
        source_key.setObjectName("MetaKey")
        self.source_label = QtWidgets.QLabel("正在打开默认考核视频…")
        self.source_label.setObjectName("MetaValue")
        self.source_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.source_info_label = QtWidgets.QLabel("")
        self.source_info_label.setObjectName("MetaKey")
        model_key = QtWidgets.QLabel("YOLO")
        model_key.setObjectName("MetaKey")
        self.model_label = QtWidgets.QLabel("等待加载…")
        self.model_label.setObjectName("MetaValue")
        meta_row.addWidget(source_key)
        meta_row.addWidget(self.source_label, 1)
        meta_row.addWidget(self.source_info_label)
        meta_row.addSpacing(10)
        meta_row.addWidget(model_key)
        meta_row.addWidget(self.model_label)
        card_layout.addLayout(meta_row)

        layout.addWidget(card, 1)

        self.pipeline = PipelineWidget()
        layout.addWidget(self.pipeline)
        return left

    def _build_right(self) -> QtWidgets.QWidget:
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)

        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(10, 0, 6, 8)
        layout.setSpacing(8)

        layout.addWidget(self._build_result_card())
        layout.addWidget(self._build_stats_card())
        layout.addWidget(self._build_comm_card())
        layout.addWidget(self._build_log_card(), 1)

        scroll.setWidget(content)
        return scroll

    def _build_result_card(self) -> QtWidgets.QWidget:
        card = self._card("当前识别结果", "置信度最高的目标")
        layout = card.content_layout  # type: ignore[attr-defined]
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(7)
        grid.setColumnStretch(1, 1)

        self.class_label = QtWidgets.QLabel("—")
        self.class_label.setObjectName("ClassValue")
        self.waste_label = QtWidgets.QLabel("—")
        self.waste_label.setObjectName("WasteValue")
        self.confidence_label = QtWidgets.QLabel("—")
        self.confidence_label.setObjectName("ConfValue")
        self.confidence_bar = QtWidgets.QProgressBar()
        self.confidence_bar.setRange(0, 100)
        self.confidence_bar.setValue(0)
        self.confidence_bar.setTextVisible(False)
        self.confidence_bar.setFixedWidth(112)
        self.box_label = QtWidgets.QLabel("—")
        self.box_label.setObjectName("MetaValue")

        rows = [("模型类别", self.class_label), ("垃圾分类", self.waste_label)]
        for row, (key, widget) in enumerate(rows):
            key_label = QtWidgets.QLabel(key)
            key_label.setObjectName("MetaKey")
            grid.addWidget(key_label, row, 0, QtCore.Qt.AlignTop)
            grid.addWidget(widget, row, 1, 1, 2)

        conf_key = QtWidgets.QLabel("置信度")
        conf_key.setObjectName("MetaKey")
        grid.addWidget(conf_key, 2, 0, QtCore.Qt.AlignVCenter)
        conf_box = QtWidgets.QHBoxLayout()
        conf_box.setSpacing(10)
        conf_box.addWidget(self.confidence_label)
        conf_box.addWidget(self.confidence_bar)
        conf_box.addStretch(1)
        grid.addLayout(conf_box, 2, 1, 1, 2)

        box_key = QtWidgets.QLabel("框尺寸")
        box_key.setObjectName("MetaKey")
        grid.addWidget(box_key, 3, 0, QtCore.Qt.AlignVCenter)
        grid.addWidget(self.box_label, 3, 1, 1, 2)

        layout.addLayout(grid)
        return card

    def _build_stats_card(self) -> QtWidgets.QWidget:
        card = self._card("分类统计", "仅 ACTION_DONE 后 +1")
        layout = card.content_layout  # type: ignore[attr-defined]

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(8)
        head_key = QtWidgets.QLabel("类别")
        head_key.setObjectName("CardHint")
        head.addWidget(head_key)
        head.addStretch(1)
        head_count = QtWidgets.QLabel("数量")
        head_count.setObjectName("CardHint")
        head_count.setFixedWidth(38)
        head_count.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        head.addWidget(head_count)
        head_bin = QtWidgets.QLabel("桶位")
        head_bin.setObjectName("CardHint")
        head_bin.setFixedWidth(52)
        head_bin.setAlignment(QtCore.Qt.AlignCenter)
        head.addWidget(head_bin)
        layout.addLayout(head)

        for waste_type in WASTE_ORDER:
            name = WASTE_NAMES[waste_type]
            row = QtWidgets.QVBoxLayout()
            row.setSpacing(3)

            line = QtWidgets.QHBoxLayout()
            line.setSpacing(8)
            dot = QtWidgets.QLabel("●")
            dot.setStyleSheet("color: {}; font-size: 11px;".format(WASTE_COLORS[name]))
            label = QtWidgets.QLabel(name)
            label.setObjectName("CountName")
            count = QtWidgets.QLabel("0")
            count.setObjectName("CountValue")
            count.setFixedWidth(38)
            count.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            status = QtWidgets.QLabel("正常")
            status.setFixedWidth(52)
            status.setAlignment(QtCore.Qt.AlignCenter)
            self.count_labels[name] = count
            self.bin_labels[name] = status

            line.addWidget(dot)
            line.addWidget(label)
            line.addStretch(1)
            line.addWidget(count)
            line.addWidget(status)
            row.addLayout(line)

            bar = QtWidgets.QProgressBar()
            bar.setRange(0, 1)
            bar.setValue(0)
            bar.setTextVisible(False)
            bar.setFixedHeight(4)
            bar.setStyleSheet(
                "QProgressBar{height:4px;border:none;border-radius:2px;background:#E2E8F0;}"
                "QProgressBar::chunk{border-radius:2px;background:%s;}" % WASTE_COLORS[name]
            )
            self.count_bars[name] = bar
            row.addWidget(bar)
            layout.addLayout(row)
            self._set_bin_label(status, False)

        total_row = QtWidgets.QHBoxLayout()
        total_key = QtWidgets.QLabel("下位机确认总数")
        total_key.setObjectName("MetaKey")
        self.total_label = QtWidgets.QLabel("0")
        self.total_label.setObjectName("TotalValue")
        total_row.addWidget(total_key)
        total_row.addStretch(1)
        total_row.addWidget(self.total_label)
        layout.addLayout(total_row)
        return card

    def _build_comm_card(self) -> QtWidgets.QWidget:
        card = self._card("下位机通信", "TCP / 串口")
        layout = card.content_layout  # type: ignore[attr-defined]

        self.connection_info_label = QtWidgets.QLabel("等待连接…")
        self.connection_info_label.setObjectName("MetaValue")
        layout.addWidget(self.connection_info_label)

        traffic = QtWidgets.QHBoxLayout()
        traffic.setSpacing(24)

        def metric(key: str, color: str):
            column = QtWidgets.QVBoxLayout()
            column.setSpacing(2)
            column.setContentsMargins(0, 0, 0, 0)
            value = QtWidgets.QLabel("0")
            value.setObjectName("TrafficValue")
            value.setStyleSheet("color: {};".format(color))
            key_label = QtWidgets.QLabel(key)
            key_label.setObjectName("TrafficKey")
            column.addWidget(value)
            column.addWidget(key_label)
            wrapper = QtWidgets.QWidget()
            wrapper.setLayout(column)
            traffic.addWidget(wrapper)
            return value

        self.tx_label = metric("已发送帧 TX", "#0369A1")
        self.rx_label = metric("已接收帧 RX", "#15803D")
        traffic.addStretch(1)
        layout.addLayout(traffic)
        return card

    def _build_log_card(self) -> QtWidgets.QWidget:
        clear_button = QtWidgets.QPushButton("清空")
        clear_button.setObjectName("SmallButton")
        clear_button.setToolTip("清空日志显示（不影响统计）")
        card = self._card("通信日志", "TX / RX 原始帧", right=clear_button)
        layout = card.content_layout  # type: ignore[attr-defined]

        self.log_browser = LogView()
        self.log_browser.setObjectName("LogView")
        self.log_browser.setReadOnly(True)
        self.log_browser.setMaximumBlockCount(800)
        self.log_browser.setMinimumHeight(120)
        self.log_browser.setPlaceholderText("等待通信…")
        clear_button.clicked.connect(self.log_browser.clear)
        layout.addWidget(self.log_browser, 1)
        return card

    def _build_footer(self) -> QtWidgets.QWidget:
        footer = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(footer)
        layout.setContentsMargins(16, 6, 16, 12)
        layout.setSpacing(8)

        # 输入源只有一个入口：视频和摄像头在同一个对话框里选择。
        self.source_button = QtWidgets.QPushButton("导入 / 摄像头")
        self.source_button.setToolTip("同一个窗口里选择本地视频或摄像头（V / C 也可）")
        self.video_button = self.source_button
        self.camera_button = self.source_button

        self.replay_button = QtWidgets.QPushButton("重新播放")
        self.replay_button.setToolTip("从第 0 帧重新播放当前视频（R）")
        self.replay_button.setEnabled(False)

        self.reset_button = QtWidgets.QPushButton("重置统计")
        self.reset_button.setToolTip("清零四类计数与满载状态")
        self.start_button = QtWidgets.QPushButton("开始识别")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.setToolTip("开始 / 暂停识别（空格）")
        self.start_button.setEnabled(False)
        self.quit_button = QtWidgets.QPushButton("退出")
        self.quit_button.setObjectName("DangerButton")
        self.quit_button.setToolTip("停止工作线程并释放摄像头 / 视频")

        self.hint_label = QtWidgets.QLabel("空格 开始/暂停 · ←/→ 快退快进 5 秒 · R 重播 · V 视频 · C 摄像头")
        self.hint_label.setObjectName("CardHint")

        layout.addWidget(self.source_button)
        layout.addWidget(self.replay_button)
        layout.addStretch(1)
        layout.addWidget(self.hint_label)
        layout.addStretch(1)
        layout.addWidget(self.reset_button)
        layout.addWidget(self.start_button)
        layout.addWidget(self.quit_button)
        return footer

    # ================================================================ 信号
    def _connect_signals(self) -> None:
        self.source_button.clicked.connect(lambda: self.import_video())
        self.replay_button.clicked.connect(self.replay)
        self.start_button.clicked.connect(self.toggle_processing)
        self.reset_button.clicked.connect(self.reset_statistics)
        self.quit_button.clicked.connect(self.close)

        self.progress_slider.sliderPressed.connect(self._on_slider_pressed)
        self.progress_slider.sliderReleased.connect(self._on_slider_released)

        self.worker.frame_ready.connect(self.update_frame)
        self.worker.state_changed.connect(self._on_state_changed)
        self.worker.counts_changed.connect(self.update_counts)
        self.worker.bins_changed.connect(self.update_bins)
        self.worker.detection_changed.connect(self.update_detection)
        self.worker.model_changed.connect(self.model_label.setText)
        self.worker.source_changed.connect(self.on_source_changed)
        self.worker.source_info.connect(self._on_source_info)
        self.worker.connection_info.connect(self._on_connection_info)
        self.worker.traffic_changed.connect(self._on_traffic)
        self.worker.source_finished.connect(self.on_source_finished)
        self.worker.log_message.connect(self.append_log)
        self.worker.connection_changed.connect(self.update_connection)
        self.worker.fps_changed.connect(self.update_fps)
        self.worker.progress_changed.connect(self.update_progress)

        QtWidgets.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Space), self,
                            activated=self.toggle_processing)
        QtWidgets.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Left), self,
                            activated=lambda: self._seek_by(-5))
        QtWidgets.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Right), self,
                            activated=lambda: self._seek_by(5))
        QtWidgets.QShortcut(QtGui.QKeySequence("R"), self, activated=self.replay)
        QtWidgets.QShortcut(QtGui.QKeySequence("V"), self,
                            activated=lambda: self.import_video(initial="video"))
        QtWidgets.QShortcut(QtGui.QKeySequence("C"), self,
                            activated=lambda: self.import_video(initial="camera"))

    @QtCore.pyqtSlot()
    def _initialize_worker(self) -> None:
        try:
            self.worker.prepare_model()
        except Exception as exc:
            self.model_label.setText("加载失败")
            self._on_state_changed("运行异常")
            self.append_log("YOLO 模型加载失败：{}".format(exc))
            self.start_button.setEnabled(False)
            return
        self.worker.start()
        self.start_button.setEnabled(True)
        if self._auto_start:
            QtCore.QTimer.singleShot(500, self.toggle_processing)

    # ================================================================ 输入源
    @QtCore.pyqtSlot()
    def import_video(self, initial: str = "video") -> None:
        """打开“选择输入源”窗口（视频 / 摄像头在同一个窗口里）。"""
        dialog = SourceDialog(self, initial=initial, last_dir=self._last_video_dir)
        dialog.raise_()
        dialog.activateWindow()
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            self.append_log("已取消选择输入源")
            return
        self._apply_source(dialog.kind, dialog.value)

    @QtCore.pyqtSlot()
    def open_camera(self) -> None:
        """兼容入口：直接打开摄像头页签。"""
        self.import_video(initial="camera")

    def _apply_source(self, kind: str, value: str) -> None:
        if kind == "video":
            self._last_video_dir = str(Path(value).parent)
            self.append_log("选择视频文件：{}".format(value))
            self.camera_label.set_placeholder("正在打开视频…")
        else:
            self.append_log("正在打开摄像头 {} …".format(value))
            self.camera_label.set_placeholder("正在打开摄像头 {} …".format(value))
        self.source_badge.setText("正在打开…")
        self.worker.request_source(kind, value)
        self.start_button.setEnabled(True)

    # ================================================================ 拖放
    def _on_video_dropped(self, path: str) -> None:
        """把视频拖进窗口直接作为输入源。"""
        if not Path(path).is_file():
            self.append_log("拖入的文件不存在：{}".format(path))
            return
        if probe_video(path) is None:
            self.append_log("拖入的文件无法解码，可能不是视频：{}".format(Path(path).name))
            return
        self.append_log("拖入视频：{}".format(Path(path).name))
        self._apply_source("video", path)

    # ================================================================ 操作
    @QtCore.pyqtSlot()
    def replay(self) -> None:
        if self._is_camera:
            self.append_log("摄像头是实时流，无法重新播放")
            return
        self.worker.request_replay()
        self.append_log("请求从第 0 帧重新播放")
        if not self._processing:
            self._set_processing(True)

    @QtCore.pyqtSlot()
    def reset_statistics(self) -> None:
        self.worker.request_reset()
        self.append_log("统计已重置，等待新的识别结果")

    def _set_processing(self, enabled: bool) -> None:
        self._processing = enabled
        if enabled:
            self.worker.start_processing()
            self.start_button.setText("暂停识别")
        else:
            self.worker.pause_processing()
            self.start_button.setText("开始识别")

    @QtCore.pyqtSlot()
    def toggle_processing(self) -> None:
        if not self.start_button.isEnabled():
            return
        self._set_processing(not self._processing)
        self.append_log("视觉识别已{}".format("启动" if self._processing else "暂停"))

    def _seek_by(self, seconds: int) -> None:
        if self._total_frames <= 0 or not self.progress_slider.isEnabled():
            return
        if self._source_fps <= 0:
            return
        step = int(seconds * self._source_fps * 1000.0 / self._total_frames)
        target = max(0, min(1000, self.progress_slider.value() + step))
        self.progress_slider.setValue(target)
        frame = int(target / 1000.0 * self._total_frames)
        self.worker.request_seek(frame)

    def _on_slider_pressed(self) -> None:
        self._slider_dragging = True

    def _on_slider_released(self) -> None:
        self._slider_dragging = False
        if self._total_frames <= 0:
            return
        frame = int(self.progress_slider.value() / 1000.0 * self._total_frames)
        self.worker.request_seek(frame)

    # ================================================================ 槽函数
    @QtCore.pyqtSlot()
    def on_source_finished(self) -> None:
        self._processing = False
        self.start_button.setText("重新播放")

    @QtCore.pyqtSlot(str)
    def on_source_changed(self, name: str) -> None:
        self.source_label.setText(name)
        self._is_camera = name.startswith("摄像头")
        self.source_badge.setText("实时流" if self._is_camera else "视频文件")
        self.camera_label.set_placeholder(
            "摄像头实时画面" if self._is_camera else "点击底部“导入 / 摄像头”，或把视频文件拖进窗口"
        )
        self.camera_label.clear_frame()
        self.replay_button.setEnabled(not self._is_camera)
        if self._is_camera:
            self.progress_slider.setEnabled(False)
            self.position_label.setText("00:00")
            self.duration_label.setText("--:--")
            self.frame_label.setText("实时")
        else:
            self.position_label.setText("00:00")
            self.frame_label.setText("第 0 / 0 帧")

        first_source = not self._source_ready_once
        self._source_ready_once = True
        # 切换输入源后立即开始取帧，避免画面停在占位状态。
        if not first_source and not self._processing:
            self._set_processing(True)
            self.append_log("已自动开始取帧，可直接观察画面")

    @QtCore.pyqtSlot(str)
    def _on_source_info(self, text: str) -> None:
        self.source_info_label.setText(text)

    @QtCore.pyqtSlot(str)
    def _on_connection_info(self, text: str) -> None:
        self.connection_info_label.setText(text)

    @QtCore.pyqtSlot(int, int)
    def _on_traffic(self, tx: int, rx: int) -> None:
        self.tx_label.setText(str(tx))
        self.rx_label.setText(str(rx))

    @QtCore.pyqtSlot(QtGui.QImage)
    def update_frame(self, image: QtGui.QImage) -> None:
        self.camera_label.set_frame(image)

    @QtCore.pyqtSlot(int, int, float)
    def update_progress(self, current: int, total: int, source_fps: float = 30.0) -> None:
        self._total_frames = max(0, int(total))
        self._source_fps = float(source_fps) if source_fps and source_fps > 0 else 30.0
        if total <= 0:
            self.progress_slider.setEnabled(False)
            if self._is_camera:
                self.position_label.setText("00:00")
                self.duration_label.setText("--:--")
                self.frame_label.setText("实时")
            return
        self.progress_slider.setEnabled(True)
        self.frame_label.setText("第 {} / {} 帧".format(current, total))
        position = current / self._source_fps
        duration = total / self._source_fps
        self.position_label.setText(_format_time(position))
        self.duration_label.setText(_format_time(duration))
        if not self._slider_dragging:
            self.progress_slider.blockSignals(True)
            self.progress_slider.setValue(int(1000.0 * current / total) if total else 0)
            self.progress_slider.blockSignals(False)

    @QtCore.pyqtSlot(object)
    def update_detection(self, detection: Optional[Detection]) -> None:
        if detection is None:
            self.class_label.setText("—")
            self.waste_label.setText("—")
            self.waste_label.setStyleSheet("")
            self.confidence_label.setText("—")
            self.confidence_bar.setValue(0)
            self.box_label.setText("—")
            return
        name = WASTE_NAMES[detection.waste_type]
        color = WASTE_COLORS[name]
        x1, y1, x2, y2 = detection.box
        self.class_label.setText(detection.class_name)
        self.waste_label.setText(name)
        self.waste_label.setStyleSheet("color: {};".format(color))
        self.confidence_label.setText("{:.1f}%".format(detection.confidence * 100))
        self.confidence_bar.setValue(int(round(detection.confidence * 100)))
        self.confidence_bar.setStyleSheet(
            "QProgressBar{height:7px;border:none;border-radius:3px;background:#E2E8F0;}"
            "QProgressBar::chunk{border-radius:3px;background:%s;}" % color
        )
        self.box_label.setText("{} × {} px".format(max(0, x2 - x1), max(0, y2 - y1)))

    @QtCore.pyqtSlot(object)
    def update_counts(self, values: dict) -> None:
        total = 0
        for name, value in values.items():
            total += int(value)
            if name in self.count_labels:
                self.count_labels[name].setText(str(value))
        self.total_label.setText(str(total))
        for name, bar in self.count_bars.items():
            count = int(values.get(name, 0))
            bar.setRange(0, max(1, total))
            bar.setValue(count)

    @QtCore.pyqtSlot(object)
    def update_bins(self, values: dict) -> None:
        for name, is_full in values.items():
            label = self.bin_labels.get(name)
            if label is not None:
                self._set_bin_label(label, bool(is_full))

    def _set_bin_label(self, label: QtWidgets.QLabel, is_full: bool) -> None:
        if is_full:
            label.setText("满载")
            label.setStyleSheet(
                "color:#B91C1C; background:#FEE2E2; border:1px solid #FECACA;"
                "border-radius:7px; padding:2px 0; font-size:11px; font-weight:600;"
            )
        else:
            label.setText("正常")
            label.setStyleSheet(
                "color:#15803D; background:#DCFCE7; border:1px solid #BBF7D0;"
                "border-radius:7px; padding:2px 0; font-size:11px; font-weight:600;"
            )

    @QtCore.pyqtSlot(str)
    def _on_state_changed(self, text: str) -> None:
        self.state_label.setText(text)
        self._paint_state(text)
        self.pipeline.set_state(text)
        if text == "输入源不可用":
            # 切换失败：把画面占位和徽标恢复，避免一直停在“正在打开…”。
            self.source_badge.setText("实时流" if self._is_camera else "视频文件")
            self.camera_label.set_placeholder("输入源不可用：请重新导入视频或打开摄像头")
            self.camera_label.clear_frame()

    @QtCore.pyqtSlot(str)
    def append_log(self, message: str) -> None:
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        if message.startswith("TX"):
            color = "#0369A1"
        elif message.startswith("RX"):
            color = "#15803D"
        elif any(word in message for word in ("失败", "异常", "错误", "不可用", "无法")):
            color = "#B91C1C"
        else:
            color = "#334155"
        self.log_browser.appendHtml(
            '<span style="color:#94A3B8">[{}]</span> '
            '<span style="color:{}">{}</span>'.format(timestamp, color, html_escape(message))
        )
        scrollbar = self.log_browser.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    @QtCore.pyqtSlot(bool)
    def update_connection(self, connected: bool) -> None:
        self.connection_label.setText("已连接" if connected else "未连接")
        self._paint_connection(connected)

    @QtCore.pyqtSlot(float)
    def update_fps(self, value: float) -> None:
        self.fps_label.setText("{:.0f} FPS".format(value))

    def _paint_state(self, text: str) -> None:
        color = STATE_COLORS.get(text, "#475569")
        self.state_label.setStyleSheet(
            "color: {}; border: 1px solid {}; background: #FFFFFF;"
            "border-radius: 13px; padding: 6px 15px; font-weight: 600;".format(color, color)
        )

    def _paint_connection(self, connected: bool) -> None:
        color = "#15803D" if connected else "#DC2626"
        self.connection_label.setStyleSheet(
            "color: {}; border: 1px solid {}; background: #FFFFFF;"
            "border-radius: 13px; padding: 6px 15px; font-weight: 600;".format(color, color)
        )

    # ================================================================ 退出
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.append_log("正在停止工作线程并释放摄像头/视频…")
        self.worker.stop()
        if not self.worker.wait(5000):
            self.append_log("工作线程未在规定时间内退出")
        event.accept()


