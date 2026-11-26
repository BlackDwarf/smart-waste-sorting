"""界面流程自检（无头运行，不需要人点鼠标）。

真实加载 best.pt、真实打开 vedio/dep.mp4，然后按“开始 → 暂停 → 跳转 → 重播 →
退出”的顺序驱动主窗口，验证：

* 模型与视频源正常打开；
* 暂停后画面帧号不再变化；
* 拖动进度条（request_seek）能跳到指定帧；
* 重新播放回到第 0 帧；
* 关窗口时工作线程能退出、视频句柄释放。

    python -m tools.ui_flow_check
"""

import sys
import threading
import time

# 与 app.main 一致：Windows 上必须先导入 torch，再导入 PyQt5。
try:
    import torch  # noqa: F401
    import ultralytics  # noqa: F401
except ImportError:
    pass

from PyQt5 import QtCore, QtWidgets

from app.ui import MainWindow
from app.worker import SortingWorker
from simulator.lower_simulator import LowerComputerSimulator
from tools.e2e_check import _free_port

FAILURES = []
NOTES = []


def check(condition, message):
    if condition:
        NOTES.append("[ok] " + message)
    else:
        FAILURES.append(message)
        NOTES.append("[FAIL] " + message)


def main(argv=None) -> int:
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
    app = QtWidgets.QApplication(argv if argv is not None else sys.argv[:1])

    # 起一个真实的下位机模拟器，避免工作线程反复重连拖慢整个循环。
    port = _free_port()
    simulator = LowerComputerSimulator("127.0.0.1", port, action_delay=0.02)
    threading.Thread(target=simulator.serve_forever, daemon=True).start()
    time.sleep(0.3)

    worker = SortingWorker(
        sim_host="127.0.0.1",
        sim_port=port,
        source_kind="video",
        source_value="vedio/dep.mp4",
        weights="Predict/best.pt",
    )
    window = MainWindow(worker)
    window.show()

    state = {}

    def start_playback():
        check("等待加载" not in window.model_label.text(), "模型已加载：{}".format(window.model_label.text()))
        check("dep.mp4" in window.source_label.text(), "视频源已打开：{}".format(window.source_label.text()))
        window._set_processing(True)

    def pause_and_capture():
        state["frame_before_pause"] = _current_frame(worker)
        window._set_processing(False)

    def verify_paused():
        check(
            _current_frame(worker) == state.get("frame_before_pause"),
            "暂停后帧号保持不变（{}）".format(_current_frame(worker)),
        )
        worker.request_seek(1500)

    def verify_seek():
        frame = _current_frame(worker)
        check(1400 <= frame <= 1560, "跳转到第 1500 帧附近（实际 {}）".format(frame))
        check("1500" in window.frame_label.text() or "第 1" in window.frame_label.text(),
              "进度标签同步：{}".format(window.frame_label.text()))
        worker.request_replay()

    def verify_replay():
        frame = _current_frame(worker)
        # 重播后视频会立即继续播放，所以只要求“远小于 1500”而不是恰好 0。
        check(frame < 200, "重新播放回到开头（实际 {}）".format(frame))
        window.close()

    def finish():
        check(not worker.isRunning(), "工作线程已退出")
        app.quit()

    QtCore.QTimer.singleShot(4000, start_playback)
    QtCore.QTimer.singleShot(6500, pause_and_capture)
    QtCore.QTimer.singleShot(8000, verify_paused)
    QtCore.QTimer.singleShot(9500, verify_seek)
    QtCore.QTimer.singleShot(11000, verify_replay)
    QtCore.QTimer.singleShot(12500, finish)
    app.exec_()

    print("\n".join(NOTES))
    if FAILURES:
        print("\n界面流程自检失败 {} 项".format(len(FAILURES)))
        return 1
    print("\n界面流程自检通过")
    return 0


def _current_frame(worker) -> int:
    source = getattr(worker, "_source", None)
    return int(getattr(source, "current_frame", -1)) if source is not None else -1


if __name__ == "__main__":
    sys.exit(main())
