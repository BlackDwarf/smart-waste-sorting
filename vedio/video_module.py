"""供 YOLO 逐帧处理的视频文件模块。

原比赛代码使用 QMediaPlayer 直接播放视频，画面无法可靠地逐帧交给 YOLO。
本考核保留原 ``vedio`` 目录名，但统一使用 OpenCV 输出 BGR 帧：读到的每一帧
就是送进 ``YoloDetector.detect`` 的那一帧，播放进度和识别进度因此严格一致。
"""

from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np


class VideoFileSource:
    """视频文件输入源（逐帧读取 / 跳转 / 重播 / 释放）。"""

    kind = "video"

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError("视频文件不存在：{}".format(self.path))
        self.display_name = str(self.path)
        self.cap = cv2.VideoCapture(str(self.path))
        if not self.cap.isOpened():
            raise RuntimeError("无法打开视频（格式不支持或文件损坏）：{}".format(self.path))
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.source_fps = float(self.cap.get(cv2.CAP_PROP_FPS))
        self.frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        self.duration_seconds = (
            self.frame_count / self.source_fps if self.source_fps > 0 else 0.0
        )
        self.decode_error = False
        self._released = False

    # ------------------------------------------------------------------ 状态
    @property
    def current_frame(self) -> int:
        """下一帧将要读取的位置（0 基，与 OpenCV POS_FRAMES 一致）。"""
        if self.cap is None or self._released:
            return 0
        return int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))

    @property
    def position_seconds(self) -> float:
        if self.source_fps <= 0:
            return 0.0
        return self.current_frame / self.source_fps

    @property
    def progress(self) -> float:
        """0.0~1.0 的播放进度，供 UI 进度条使用。"""
        if self.frame_count <= 0:
            return 0.0
        return max(0.0, min(1.0, self.current_frame / float(self.frame_count)))

    @property
    def at_end(self) -> bool:
        """是否已经播放到结尾（用于区分“视频结束”和“解码失败”）。"""
        if self.frame_count <= 0:
            return True
        return self.current_frame >= self.frame_count

    # ------------------------------------------------------------------ 读取
    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """读取下一帧。

        返回 ``(True, frame)`` 表示成功；``(False, None)`` 表示已到结尾、
        文件已被释放或该帧解码失败（此时 ``decode_error`` 为 True）。
        """
        if self.cap is None or self._released:
            return False, None
        try:
            ok, frame = self.cap.read()
        except cv2.error:
            ok, frame = False, None
        if not ok or frame is None or getattr(frame, "size", 0) == 0:
            # 区分正常结束与解码损坏：位置已到末尾说明是播放完成。
            self.decode_error = not self.at_end
            return False, None
        self.decode_error = False
        return True, frame

    # ------------------------------------------------------------------ 跳转
    def seek_frame(self, frame_index: int) -> bool:
        """跳转到指定帧（0 基）。

        越界、负数、未打开或释放后调用都会返回 False，绝不抛异常。
        """
        if self.cap is None or self._released:
            return False
        try:
            index = int(frame_index)
        except (TypeError, ValueError):
            return False
        if index < 0:
            return False
        if self.frame_count > 0 and index >= self.frame_count:
            return False
        try:
            ok = self.cap.set(cv2.CAP_PROP_POS_FRAMES, float(index))
        except cv2.error:
            return False
        if ok:
            self.decode_error = False
        return bool(ok)

    def seek_seconds(self, seconds: float) -> bool:
        """按秒跳转，UI 进度条用。"""
        if self.source_fps <= 0:
            return False
        return self.seek_frame(int(round(float(seconds) * self.source_fps)))

    def restart(self) -> bool:
        """从第 0 帧重新播放。"""
        return self.seek_frame(0)

    # ------------------------------------------------------------------ 释放
    def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self.cap is not None:
            try:
                self.cap.release()
            except cv2.error:
                pass
            self.cap = None
