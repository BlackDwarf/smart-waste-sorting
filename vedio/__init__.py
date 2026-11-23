"""视频文件输入模块（目录名沿用原比赛项目的 ``vedio``）。

对外只暴露 :class:`VideoFileSource`：逐帧读取 BGR 帧、跳转、重播与释放。
"""

from .video_module import VideoFileSource

__all__ = ["VideoFileSource"]
