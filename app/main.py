"""Application entry point."""

import argparse
import os
import sys
from pathlib import Path


# Some Conda-created Windows virtual environments do not expose PyQt's platform
# plugin directory correctly. Docker/Linux is unaffected.
if os.name == "nt" and "QT_QPA_PLATFORM_PLUGIN_PATH" not in os.environ:
    plugin_dir = Path(sys.prefix) / "Lib" / "site-packages" / "PyQt5" / "Qt5" / "plugins" / "platforms"
    if plugin_dir.exists():
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(plugin_dir)


def parse_args():
    parser = argparse.ArgumentParser(description="智能垃圾分拣招新考核程序")
    parser.add_argument("--sim-host", default=os.environ.get("SIM_HOST", "127.0.0.1"))
    parser.add_argument("--sim-port", default=int(os.environ.get("SIM_PORT", "9000")), type=int)
    parser.add_argument("--transport", choices=("tcp", "serial"), default=os.environ.get("TRANSPORT", "tcp"))
    parser.add_argument("--serial-port", default=os.environ.get("SERIAL_PORT", "/dev/ttyUSB0"))
    parser.add_argument("--baudrate", default=int(os.environ.get("BAUDRATE", "9600")), type=int)
    parser.add_argument(
        "--source",
        choices=("video", "camera"),
        default=os.environ.get("SOURCE", "video"),
    )
    parser.add_argument(
        "--source-value",
        default=os.environ.get("SOURCE_VALUE", "assets/assessment_demo.mp4"),
    )
    parser.add_argument("--weights", default=os.environ.get("YOLO_WEIGHTS", "Predict/best.pt"))
    parser.add_argument("--confidence", default=float(os.environ.get("YOLO_CONFIDENCE", "0.50")), type=float)
    parser.add_argument("--auto-start", action="store_true")
    return parser.parse_args()


def _preload_inference_stack() -> None:
    """在导入 PyQt5 之前先把 torch / ultralytics 拉进进程。

    Windows 上如果 PyQt5 先于 torch 导入，torch 的 DLL 初始化会失败
    （``WinError 1114``，`c10.dll` 加载失败）。先把推理栈加载进来可以稳定
    避开这个导入顺序问题；Linux（Docker）上也没有副作用，只是提前几秒。
    """
    try:
        import torch  # noqa: F401
    except ImportError:
        return
    try:
        import ultralytics  # noqa: F401
    except ImportError:
        pass


def main() -> None:
    _preload_inference_stack()

    from PyQt5 import QtCore, QtGui, QtWidgets

    from .ui import MainWindow
    from .worker import SortingWorker

    args = parse_args()
    # 高分屏：按 DPI 缩放、位图用高分辨率版本，字体用完整 hinting，文字更锐利。
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(sys.argv)
    default_font = app.font()
    try:
        default_font.setHintingPreference(QtGui.QFont.PreferFullHinting)
    except AttributeError:  # 老版本 Qt 没有这个枚举时忽略
        pass
    app.setFont(default_font)
    worker = SortingWorker(
        sim_host=args.sim_host,
        sim_port=args.sim_port,
        source_kind=args.source,
        source_value=args.source_value,
        weights=args.weights,
        confidence=args.confidence,
        transport_kind=args.transport,
        serial_port=args.serial_port,
        baudrate=args.baudrate,
    )
    window = MainWindow(worker, auto_start=args.auto_start)
    _fit_to_screen(window)
    if os.name != "nt":
        # Docker/Xvfb 这类虚拟桌面直接最大化，避免窗口四周留黑边。
        window.showMaximized()
    else:
        window.show()
    sys.exit(app.exec_())


def _fit_to_screen(window) -> None:
    """窗口比屏幕大时（例如 Docker 里的 Xvfb 只有 1280×850）自动缩到可用区域。

    只在小屏幕上缩放，正常桌面仍使用界面默认的 1360×860。
    """
    from PyQt5 import QtWidgets

    screen = QtWidgets.QApplication.primaryScreen()
    if screen is None:
        return
    available = screen.availableGeometry()
    width = min(window.width(), available.width() - 16)
    height = min(window.height(), available.height() - 16)
    if (width, height) != (window.width(), window.height()):
        window.resize(
            max(window.minimumWidth(), width),
            max(window.minimumHeight(), height),
        )
        frame_top_left = window.frameGeometry().topLeft()
        window.move(
            available.center().x() - window.width() // 2 - (frame_top_left.x() - window.x()),
            available.center().y() - window.height() // 2 - (frame_top_left.y() - window.y()),
        )


if __name__ == "__main__":
    main()
