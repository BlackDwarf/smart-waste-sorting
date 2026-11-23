"""视频输入源的读取、跳转、重播与释放测试。"""

import unittest
from pathlib import Path

from app.frame_sources import create_frame_source
from vedio.video_module import VideoFileSource


DEMO = Path("assets/assessment_demo.mp4")
LONG = Path("vedio/dep.mp4")


class VideoSourceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(DEMO.is_file(), "缺少考核演示视频")
        self.source = VideoFileSource(str(DEMO))

    def tearDown(self):
        self.source.release()

    def test_metadata_is_exposed_for_progress_display(self):
        self.assertGreater(self.source.frame_count, 0)
        self.assertGreater(self.source.source_fps, 0)
        self.assertAlmostEqual(
            self.source.duration_seconds,
            self.source.frame_count / self.source.source_fps,
            places=3,
        )
        self.assertEqual(self.source.progress, 0.0)

    def test_progress_grows_while_reading(self):
        self.assertTrue(self.source.read()[0])
        for _ in range(5):
            self.source.read()
        self.assertGreater(self.source.progress, 0.0)
        self.assertLessEqual(self.source.progress, 1.0)
        self.assertGreater(self.source.position_seconds, 0.0)

    def test_seek_out_of_range_is_rejected(self):
        self.assertFalse(self.source.seek_frame(-1))
        self.assertFalse(self.source.seek_frame(self.source.frame_count))
        self.assertFalse(self.source.seek_frame(self.source.frame_count + 100))

    def test_seek_to_middle_returns_expected_frame_number(self):
        target = min(50, self.source.frame_count - 1)
        self.assertTrue(self.source.seek_frame(target))
        self.assertEqual(self.source.current_frame, target)
        ok, frame = self.source.read()
        self.assertTrue(ok)
        self.assertEqual(frame.shape[:2], (720, 1280))

    def test_seek_seconds_uses_source_fps(self):
        self.assertTrue(self.source.seek_seconds(1.0))
        self.assertAlmostEqual(self.source.position_seconds, 1.0, delta=0.2)

    def test_end_of_video_then_restart(self):
        self.assertTrue(self.source.seek_frame(self.source.frame_count - 1))
        ok, frame = self.source.read()
        self.assertTrue(ok)
        self.assertIsNotNone(frame)
        ok, frame = self.source.read()
        self.assertFalse(ok)
        self.assertIsNone(frame)
        self.assertTrue(self.source.at_end)
        self.assertTrue(self.source.restart())
        ok, restarted = self.source.read()
        self.assertTrue(ok)
        self.assertFalse(self.source.at_end)

    def test_read_after_release_is_safe(self):
        self.source.release()
        self.assertFalse(self.source.read()[0])
        self.assertFalse(self.source.seek_frame(0))
        self.source.release()  # 重复释放不应抛异常

    def test_missing_file_raises_clear_error(self):
        with self.assertRaises(FileNotFoundError):
            VideoFileSource("assets/not-exists.mp4")

    def test_factory_rejects_unknown_source(self):
        with self.assertRaises(ValueError):
            create_frame_source("rtsp")
        with self.assertRaises(ValueError):
            create_frame_source("camera", "abc")


class LongVideoTests(unittest.TestCase):
    def test_long_video_seek_and_release(self):
        self.assertTrue(LONG.is_file())
        source = create_frame_source("video", str(LONG))
        try:
            self.assertEqual(source.frame_count, 2839)
            self.assertTrue(source.seek_frame(2838))
            self.assertGreater(source.progress, 0.99)
            self.assertTrue(source.restart())
            self.assertEqual(source.current_frame, 0)
        finally:
            source.release()


if __name__ == "__main__":
    unittest.main()
