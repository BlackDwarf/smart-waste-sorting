"""YOLO 适配器：把 ultralytics 的推理结果转换成四类垃圾的 Detection。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from .protocol import WasteType


@dataclass
class Detection:
    waste_type: WasteType
    class_name: str
    confidence: float
    box: Tuple[int, int, int, int]


class Detector(ABC):
    @abstractmethod
    def detect(self, frame: np.ndarray) -> List[Detection]:
        raise NotImplementedError


def _as_float(value) -> float:
    """把 tensor / ndarray / python 标量统一成 float。"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return float(item())
        except (TypeError, ValueError, RuntimeError):
            pass
    array = np.asarray(value, dtype=float).reshape(-1)
    return float(array[0]) if array.size else 0.0


def _as_xyxy(box) -> Optional[Tuple[int, int, int, int]]:
    """把 ``box.xyxy`` 统一成 (x1, y1, x2, y2) 整数像素坐标。

    ultralytics 的 ``xyxy`` 形状是 ``(1, 4)`` 的 tensor；测试中的 Fake 模型
    给出的是 ``[_Coordinates]``（带 ``.numpy()``）。两种都兼容。
    """
    raw = getattr(box, "xyxy", None)
    if raw is None:
        return None
    try:
        first = raw[0]
    except (TypeError, IndexError, KeyError):
        return None
    if hasattr(first, "cpu"):
        first = first.cpu()
    numpy = getattr(first, "numpy", None)
    values = numpy() if callable(numpy) else first
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.size < 4:
        return None
    return tuple(int(round(float(value))) for value in array[:4])  # type: ignore[return-value]


class YoloDetector(Detector):
    """加载指定权重，并把模型原始类别映射到四类垃圾。"""

    DEFAULT_CLASS_MAP = {
        "bottolad": WasteType.RECYCLABLE,
        "plasticbottle": WasteType.RECYCLABLE,
        "box": WasteType.RECYCLABLE,
        "can": WasteType.RECYCLABLE,
        "papercup": WasteType.RECYCLABLE,
        "yangleduo": WasteType.RECYCLABLE,
        "potato": WasteType.KITCHEN,
        "carrot": WasteType.KITCHEN,
        "qincarrot": WasteType.KITCHEN,
        "redcarrot": WasteType.KITCHEN,
        "whitcarrot": WasteType.KITCHEN,
        "battery": WasteType.HAZARDOUS,
        "drug": WasteType.HAZARDOUS,
        "cobblestone": WasteType.OTHER,
        "porcelain": WasteType.OTHER,
    }

    def __init__(
        self,
        weights: Optional[str] = None,
        model=None,
        confidence: float = 0.50,
        device: Optional[str] = None,
    ) -> None:
        if not 0.0 < confidence <= 1.0:
            raise ValueError("置信度阈值必须在 (0, 1] 范围内")
        if model is None:
            if not weights:
                raise ValueError("必须指定 YOLO 权重文件")
            weight_path = Path(weights)
            if not weight_path.is_file():
                raise FileNotFoundError("YOLO 权重不存在：{}".format(weight_path))
            try:
                import torch
                from ultralytics import YOLO
            except ImportError as exc:
                raise RuntimeError("未安装 YOLO 运行环境") from exc
            self.device = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
            self.model = YOLO(str(weight_path))
        else:
            self.model = model
            self.device = device or "cpu"

        self.confidence = confidence
        model_names = getattr(self.model, "names", {})
        unknown = sorted(set(model_names.values()) - set(self.DEFAULT_CLASS_MAP))
        if unknown:
            raise ValueError("权重中存在未配置类别：{}".format(", ".join(unknown)))

    def class_name_of(self, class_id: int) -> str:
        """按类别 id 查模型原始类别名（优先使用本次推理结果的 names）。"""
        names = getattr(self.model, "names", {}) or {}
        if isinstance(names, dict):
            return str(names.get(class_id, class_id))
        try:
            return str(names[class_id])
        except (IndexError, KeyError, TypeError):
            return str(class_id)

    def detect(self, frame: np.ndarray) -> List[Detection]:
        """调用 ``model.predict`` 并转换 boxes、类别和置信度。

        返回结果按置信度从高到低排序；空帧、无目标、未知类别都不会抛异常，
        只会得到空列表或跳过该目标，保证视频循环不中断。
        """
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            return []

        predict_kwargs = {
            "source": frame,
            "conf": self.confidence,
            "verbose": False,
        }
        if self.device:
            predict_kwargs["device"] = self.device
        results = self.model.predict(**predict_kwargs)
        if not results:
            return []

        detections = []  # type: List[Detection]
        for result in results:
            names = getattr(result, "names", None) or getattr(self.model, "names", {}) or {}
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                confidence = _as_float(getattr(box, "conf", None))
                if confidence < self.confidence:
                    continue
                class_id = int(round(_as_float(getattr(box, "cls", None))))
                try:
                    class_name = str(names[class_id])
                except (KeyError, IndexError, TypeError):
                    class_name = str(class_id)
                waste_type = self.DEFAULT_CLASS_MAP.get(class_name)
                if waste_type is None:
                    # 未配置的类别直接跳过：不让未知目标打断整条识别链路。
                    continue
                box_coordinates = _as_xyxy(box)
                if box_coordinates is None:
                    continue
                detections.append(
                    Detection(
                        waste_type=waste_type,
                        class_name=class_name,
                        confidence=confidence,
                        box=box_coordinates,
                    )
                )

        detections.sort(key=lambda item: item.confidence, reverse=True)
        return detections
