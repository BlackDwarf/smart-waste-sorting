"""界面冒烟测试：不加载模型、不连接下位机，只验证控件装配与数据回填。

用离屏平台运行，因此 CI / Docker 里没有显示器也不会失败；未安装 PyQt5 时自动跳过。
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt5 import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover - 无 PyQt5 的环境
    QtCore = QtGui = QtWidgets = None


@unittest.skipIf(QtWidgets is None, "未安装 PyQt5")
class UiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from app.ui import MainWindow

        cls.MainWindow = MainWindow

    def setUp(self):
        from app.protocol import WasteType

        self.WasteType = WasteType
        self.worker = _StubWorker()
        self.window = self.MainWindow(self.worker)

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_key_widgets_exist(self):
        for attribute in (
            "camera_label",
            "state_label",
            "connection_label",
            "fps_label",
            "class_label",
            "waste_label",
            "confidence_label",
            "source_label",
            "model_label",
            "log_browser",
            "progress_slider",
            "video_button",
            "camera_button",
            "start_button",
            "reset_button",
            "quit_button",
            "pipeline",
            "source_badge",
            "tx_label",
            "rx_label",
            "total_label",
        ):
            self.assertTrue(hasattr(self.window, attribute), "缺少控件 " + attribute)
        self.assertEqual(len(self.window.count_labels), 4)
        self.assertEqual(len(self.window.bin_labels), 4)
        self.assertFalse(self.window.progress_slider.isEnabled())

    def test_counts_and_total_are_updated(self):
        values = {"可回收垃圾": 3, "厨余垃圾": 2, "有害垃圾": 1, "其他垃圾": 0}
        self.window.update_counts(values)
        self.assertEqual(self.window.count_labels["可回收垃圾"].text(), "3")
        self.assertEqual(self.window.total_label.text(), "6")

    def test_detection_result_is_rendered(self):
        from app.detectors import Detection
        from app.protocol import WasteType

        detection = Detection(WasteType.HAZARDOUS, "battery", 0.913, (10, 10, 60, 90))
        self.window.update_detection(detection)
        self.assertEqual(self.window.class_label.text(), "battery")
        self.assertEqual(self.window.waste_label.text(), "有害垃圾")
        self.assertIn("91.3", self.window.confidence_label.text())
        self.assertEqual(self.window.confidence_bar.value(), 91)

        self.window.update_detection(None)
        self.assertEqual(self.window.class_label.text(), "—")

    def test_progress_controls_slider_and_time_labels(self):
        self.window.update_progress(150, 300, 30.0)
        self.assertTrue(self.window.progress_slider.isEnabled())
        self.assertEqual(self.window.progress_slider.value(), 500)
        self.assertIn("150", self.window.frame_label.text())
        self.assertEqual(self.window.duration_label.text(), "00:10")

    def test_camera_source_disables_seek_bar(self):
        self.window.on_source_changed("摄像头 0")
        self.assertFalse(self.window.progress_slider.isEnabled())
        self.window._seek_by(5)  # 不应抛异常

    def test_bin_full_state_is_visible(self):
        self.window.update_bins(
            {"可回收垃圾": True, "厨余垃圾": False, "有害垃圾": False, "其他垃圾": False}
        )
        self.assertEqual(self.window.bin_labels["可回收垃圾"].text(), "满载")
        self.assertIn("B91C1C", self.window.bin_labels["可回收垃圾"].styleSheet())

    def test_log_is_append_only_text(self):
        self.window.append_log("TX  AA 55 03 01 11 03 18")
        self.assertIn("AA 55 03 01 11 03 18", self.window.log_browser.toPlainText())

    def test_state_and_connection_chips_change_color(self):
        self.window._on_state_changed("通信异常")
        self.assertIn("#DC2626", self.window.state_label.styleSheet())
        self.window.update_connection(True)
        self.assertEqual(self.window.connection_label.text(), "已连接")

    def test_pipeline_follows_state_machine(self):
        self.window._on_state_changed("等待下位机确认")
        # 第 1 步已完成（绿色），第 2 步是高亮当前步
        self.assertIn("#16A34A", self.window.pipeline.steps[0].styleSheet())
        self.assertIn("#2563EB", self.window.pipeline.steps[1].styleSheet())
        self.window._on_state_changed("通信异常")
        self.assertIn("#DC2626", self.window.pipeline.steps[0].styleSheet())

    def test_traffic_counters_and_connection_info(self):
        self.window._on_traffic(12, 11)
        self.assertEqual(self.window.tx_label.text(), "12")
        self.assertEqual(self.window.rx_label.text(), "11")
        self.window._on_connection_info("TCP lower-sim:9000")
        self.assertIn("lower-sim", self.window.connection_info_label.text())

    def test_camera_mode_disables_video_controls(self):
        self.window.on_source_changed("摄像头 0 · 1280×720")
        self.assertEqual(self.window.source_badge.text(), "实时流")
        self.assertFalse(self.window.replay_button.isEnabled())
        self.assertFalse(self.window.progress_slider.isEnabled())
        self.window.on_source_changed("assets/assessment_demo.mp4")
        self.assertEqual(self.window.source_badge.text(), "视频文件")
        self.assertTrue(self.window.replay_button.isEnabled())

    def test_source_dialog_combines_video_and_camera(self):
        from app.ui import SourceDialog

        dialog = SourceDialog(self.window, initial="video")
        try:
            self.assertEqual(dialog.tabs.count(), 2)
            self.assertEqual(dialog.tabs.tabText(0), "本地视频")
            self.assertEqual(dialog.tabs.tabText(1), "摄像头")
            self.assertFalse(dialog.open_button.isEnabled())

            dialog._set_video("vedio/dep.mp4")
            self.assertTrue(dialog.open_button.isEnabled())
            self.assertIn("2839", dialog.video_info.text())

            dialog._set_video("README.md")
            self.assertFalse(dialog.open_button.isEnabled())
            self.assertIn("不支持的扩展名", dialog.video_info.text())
        finally:
            dialog.reject()



if QtWidgets is None:  # pragma: no cover - 没有 PyQt5 时不需要替身
    _StubWorker = None
else:

    class _StubWorker(QtCore.QObject):
        """只实现界面需要的信号与槽，避免测试依赖 YOLO / 网络。"""

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


if __name__ == "__main__":
    unittest.main()

