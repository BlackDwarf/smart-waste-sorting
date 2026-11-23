import unittest
from pathlib import Path

import numpy as np

from app.detectors import YoloDetector
from app.frame_sources import create_frame_source
from app.protocol import WasteType


class VideoSourceTests(unittest.TestCase):
    def test_assessment_video_can_be_read_and_restarted(self):
        video = Path("assets/assessment_demo.mp4")
        self.assertTrue(video.is_file())
        source = create_frame_source("video", str(video))
        try:
            ok, frame = source.read()
            self.assertTrue(ok)
            self.assertEqual(frame.shape[:2], (720, 1280))
            self.assertGreater(source.frame_count, 300)
            self.assertTrue(source.restart())
            ok, restarted = source.read()
            self.assertTrue(ok)
            self.assertEqual(restarted.shape, frame.shape)
        finally:
            source.release()

    def test_original_project_video_supports_seek_and_restart(self):
        video = Path("vedio/dep.mp4")
        self.assertTrue(video.is_file())
        source = create_frame_source("video", str(video))
        try:
            self.assertEqual(source.frame_count, 2839)
            self.assertAlmostEqual(source.source_fps, 30.0, places=1)
            ok, first = source.read()
            self.assertTrue(ok)
            self.assertEqual(first.shape[:2], (720, 1280))
            self.assertTrue(source.seek_frame(100))
            ok, later = source.read()
            self.assertTrue(ok)
            self.assertEqual(later.shape, first.shape)
            self.assertTrue(source.restart())
            self.assertLessEqual(source.current_frame, 1)
        finally:
            source.release()

    def test_synthetic_source_is_not_available(self):
        with self.assertRaises(ValueError):
            create_frame_source("synthetic")


class _Scalar:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value


class _Coordinates:
    def __init__(self, values):
        self.values = np.array(values)

    def cpu(self):
        return self

    def numpy(self):
        return self.values


class _Box:
    conf = _Scalar(0.91)
    cls = _Scalar(0)
    xyxy = [_Coordinates([10, 20, 80, 120])]


class _Result:
    names = {0: "battery"}
    boxes = [_Box()]


class _FakeYolo:
    names = {0: "battery"}

    def __init__(self):
        self.calls = []

    def predict(self, **kwargs):
        self.calls.append(kwargs)
        return [_Result()]


class YoloAdapterTests(unittest.TestCase):
    def test_yolo_api_is_adapted_without_loading_real_weights(self):
        fake_model = _FakeYolo()
        detector = YoloDetector(model=fake_model)
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        output = detector.detect(frame)
        self.assertEqual(output[0].waste_type, WasteType.HAZARDOUS)
        self.assertEqual(output[0].box, (10, 20, 80, 120))
        self.assertIs(fake_model.calls[0]["source"], frame)

    def test_unknown_model_class_is_rejected(self):
        model = _FakeYolo()
        model.names = {0: "not-configured"}
        with self.assertRaises(ValueError):
            YoloDetector(model=model)


class _MultiBox:
    def __init__(self, conf, cls, xyxy):
        self.conf = _Scalar(conf)
        self.cls = _Scalar(cls)
        self.xyxy = [_Coordinates(xyxy)]


class _MultiResult:
    names = {0: "battery", 1: "papercup", 2: "potato"}
    boxes = [
        _MultiBox(0.55, 2, [5, 5, 50, 50]),
        _MultiBox(0.94, 0, [10, 10, 90, 90]),
        _MultiBox(0.72, 1, [20, 20, 60, 60]),
    ]


class _EmptyResult:
    names = {0: "battery"}
    boxes = []


class _MultiFakeYolo:
    names = _MultiResult.names

    def __init__(self, result):
        self._result = result

    def predict(self, **kwargs):
        return [self._result]


class MultiTargetTests(unittest.TestCase):
    def test_multiple_targets_are_sorted_by_confidence(self):
        detector = YoloDetector(model=_MultiFakeYolo(_MultiResult()))
        output = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))
        self.assertEqual(len(output), 3)
        confidences = [item.confidence for item in output]
        self.assertEqual(confidences, sorted(confidences, reverse=True))
        self.assertEqual(output[0].class_name, "battery")
        self.assertEqual(output[0].waste_type, WasteType.HAZARDOUS)
        self.assertEqual(output[1].waste_type, WasteType.RECYCLABLE)
        self.assertEqual(output[2].waste_type, WasteType.KITCHEN)

    def test_no_target_returns_empty_list(self):
        detector = YoloDetector(model=_MultiFakeYolo(_EmptyResult()))
        self.assertEqual(detector.detect(np.zeros((100, 100, 3), dtype=np.uint8)), [])

    def test_empty_frame_returns_empty_list(self):
        detector = YoloDetector(model=_MultiFakeYolo(_MultiResult()))
        self.assertEqual(detector.detect(np.zeros((0, 0, 3), dtype=np.uint8)), [])
        self.assertEqual(detector.detect(None), [])


if __name__ == "__main__":
    unittest.main()
