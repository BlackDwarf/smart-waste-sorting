"""统一创建视频文件和实时摄像头输入源。

摄像头部分的处理约定：

* Windows 优先用 DirectShow 打开（启动快、兼容性好），失败再退回 MSMF / 默认后端；
* 刚打开时前几帧常常读不出来，先空读“预热”，避免界面一上来就报读取失败；
* 主动申请 1280×720，摄像头不支持就自动退回它自己的默认分辨率；
* 连续读失败时自动重连设备（USB 松动、被其他软件短暂抢占）；
* 错误信息区分“不存在”“被占用”“容器内不支持”，直接告诉用户下一步怎么办。
"""

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from vedio.video_module import VideoFileSource


DEFAULT_VIDEO = "assets/assessment_demo.mp4"
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
VIDEO_SUFFIXES = (".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".m4v", ".webm")


@dataclass
class VideoInfo:
    """视频文件的基本信息，用于导入对话框的预览。"""

    path: str
    width: int
    height: int
    fps: float
    frames: int

    @property
    def duration(self) -> float:
        return self.frames / self.fps if self.fps > 0 else 0.0

    @property
    def label(self) -> str:
        return "{}×{} · {:.1f} 秒 · {} 帧".format(
            self.width or "?", self.height or "?", self.duration, self.frames
        )


def probe_video(path: str) -> Optional[VideoInfo]:
    """快速读取视频元数据；文件不存在或无法解码时返回 None。"""
    if not path:
        return None
    video_path = Path(path)
    if not video_path.is_file():
        return None
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        cap.release()
        return None
    try:
        info = VideoInfo(
            path=str(video_path),
            width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
            height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
            fps=float(cap.get(cv2.CAP_PROP_FPS) or 0.0),
            frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0),
        )
    finally:
        cap.release()
    if info.frames <= 0 and info.width <= 0:
        return None
    return info


@dataclass
class CameraInfo:
    """枚举到的一个摄像头。"""

    index: int
    width: int
    height: int
    fps: float = 0.0

    @property
    def label(self) -> str:
        size = "{}×{}".format(self.width, self.height) if self.width and self.height else "未知分辨率"
        return "摄像头 {} · {}".format(self.index, size)


def _is_container() -> bool:
    return os.path.exists("/.dockerenv")


def _backends() -> List[int]:
    if os.name != "nt":
        return [cv2.CAP_ANY]
    # DSHOW 启动更快；MSMF 兼容性更好；最后再试默认后端。
    return [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]


def open_camera(index: int) -> Optional["cv2.VideoCapture"]:
    """按后端优先级打开摄像头，全部失败返回 None。"""
    for backend in _backends():
        try:
            cap = cv2.VideoCapture(index, backend)
        except cv2.error:
            continue
        if cap is not None and cap.isOpened():
            return cap
        if cap is not None:
            cap.release()
    return None


def _warmup(cap, attempts: int = 12, delay: float = 0.08) -> bool:
    """刚打开的摄像头往往前几帧读不出来，空读几次等它出图。"""
    for _ in range(attempts):
        try:
            ok, frame = cap.read()
        except cv2.error:
            ok, frame = False, None
        if ok and frame is not None and getattr(frame, "size", 0):
            return True
        time.sleep(delay)
    return False


def _camera_error_message(index: int) -> str:
    if _is_container():
        return (
            "无法打开摄像头 {}：容器内没有摄像头设备。"
            "请在本机运行 python -m app.main --source camera".format(index)
        )
    if os.name == "nt":
        return (
            "无法打开摄像头 {}：设备不存在，或正被其他程序占用。"
            "请先关闭微信 / QQ / 钉钉 / 腾讯会议等可能占用摄像头的程序再重试".format(index)
        )
    return "无法打开摄像头 {}：设备不存在，或没有访问权限（视频组 / udev 规则）".format(index)


def probe_cameras(max_index: int = 3) -> List[CameraInfo]:
    """枚举可用摄像头（最多探测 0..max_index），用于“打开摄像头”对话框。"""
    found = []  # type: List[CameraInfo]
    for index in range(max_index + 1):
        cap = open_camera(index)
        if cap is None:
            continue
        try:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
            if not _warmup(cap, attempts=6, delay=0.05):
                continue
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            found.append(CameraInfo(index, width, height, fps))
        finally:
            cap.release()
    return found


class FrameSource(ABC):
    kind = "unknown"
    display_name = "未知图像源"
    frame_count = 0

    @abstractmethod
    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        raise NotImplementedError

    @abstractmethod
    def restart(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def release(self) -> None:
        raise NotImplementedError


class CameraFrameSource(FrameSource):
    kind = "camera"
    is_live = True

    def __init__(
        self,
        camera_index: int,
        width: int = CAMERA_WIDTH,
        height: int = CAMERA_HEIGHT,
    ) -> None:
        self.source = camera_index
        self.cap = None  # type: Optional[cv2.VideoCapture]
        self.width = 0
        self.height = 0
        self.source_fps = 30.0
        self.frame_count = 0
        self.last_error = ""
        self._failures = 0
        self._reopen_left = 3

        self.cap = open_camera(camera_index)
        if self.cap is None:
            raise RuntimeError(_camera_error_message(camera_index))

        self._configure(width, height)
        if not _warmup(self.cap):
            self.release()
            raise RuntimeError(
                "摄像头 {} 已连接但取不到画面：可能被其他程序占用，请关闭后重试".format(camera_index)
            )
        self._refresh_meta()
        self.display_name = "摄像头 {} · {}×{}".format(camera_index, self.width, self.height)

    # ------------------------------------------------------------------ 内部
    def _configure(self, width: int, height: int) -> None:
        if self.cap is None:
            return
        # 摄像头不一定支持目标分辨率，设不上也没关系，后面按真实值读回。
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 尽量降低延迟（部分后端忽略）

    def _refresh_meta(self) -> None:
        if self.cap is None:
            return
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0)
        # 很多摄像头报 0 或者离谱的值，这时按 30fps 节流。
        self.source_fps = fps if 1.0 <= fps <= 120.0 else 30.0

    def _try_reopen(self) -> None:
        """连续失败后重连一次设备（USB 松动、被短暂抢占时能自愈）。"""
        self._failures = 0
        if self._reopen_left <= 0:
            self.last_error = "摄像头连接中断，请检查设备后重新打开"
            return
        self._reopen_left -= 1
        old, self.cap = self.cap, None
        if old is not None:
            try:
                old.release()
            except cv2.error:
                pass
        self.cap = open_camera(self.source)
        if self.cap is None:
            self.last_error = _camera_error_message(self.source)
            return
        self._configure(self.width, self.height)
        _warmup(self.cap, attempts=5)

    # ------------------------------------------------------------------ 接口
    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.cap is None:
            return False, None
        try:
            ok, frame = self.cap.read()
        except cv2.error:
            ok, frame = False, None
        if ok and frame is not None and getattr(frame, "size", 0):
            self._failures = 0
            if self.width == 0:
                self._refresh_meta()
            return True, frame
        self._failures += 1
        if self._failures >= 10:
            self._try_reopen()
        return False, None

    def restart(self) -> bool:
        # 实时流没有“重新播放”的概念。
        return False

    def release(self) -> None:
        cap, self.cap = self.cap, None
        if cap is not None:
            try:
                cap.release()
            except cv2.error:
                pass


def create_frame_source(kind: str, value: str = "") -> FrameSource:
    if kind == "video":
        return VideoFileSource(value or DEFAULT_VIDEO)
    if kind == "camera":
        try:
            camera_index = int(value or 0)
        except ValueError as exc:
            raise ValueError("摄像头编号必须是整数") from exc
        if camera_index < 0:
            raise ValueError("摄像头编号不能为负数")
        return CameraFrameSource(camera_index)
    raise ValueError("未知图像源：{}；只允许 video 或 camera".format(kind))
