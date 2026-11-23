"""输入源探测测试：视频元数据、格式判断、摄像头错误信息。"""

import unittest
from pathlib import Path

from app.frame_sources import VIDEO_SUFFIXES, VideoInfo, probe_video


class ProbeVideoTests(unittest.TestCase):
    def test_reads_metadata_of_real_video(self):
        info = probe_video("assets/assessment_demo.mp4")
        self.assertIsNotNone(info)
        self.assertEqual((info.width, info.height), (1280, 720))
        self.assertGreater(info.frames, 300)
        self.assertGreater(info.duration, 0)
        self.assertIn("1280×720", info.label)

    def test_long_video_metadata(self):
        info = probe_video("vedio/dep.mp4")
        self.assertIsNotNone(info)
        self.assertEqual(info.frames, 2839)
        self.assertAlmostEqual(info.fps, 30.0, places=1)

    def test_missing_file_returns_none(self):
        self.assertIsNone(probe_video("assets/not-exists.mp4"))
        self.assertIsNone(probe_video(""))

    def test_non_video_file_returns_none(self):
        self.assertIsNone(probe_video("README.md"))

    def test_supported_suffixes(self):
        for suffix in (".mp4", ".avi", ".mov", ".mkv"):
            self.assertIn(suffix, VIDEO_SUFFIXES)
        self.assertNotIn(".txt", VIDEO_SUFFIXES)

    def test_video_info_label_and_duration(self):
        info = VideoInfo(path="x", width=1280, height=720, fps=25.0, frames=250)
        self.assertAlmostEqual(info.duration, 10.0)
        self.assertEqual(info.label, "1280×720 · 10.0 秒 · 250 帧")


if __name__ == "__main__":
    unittest.main()
