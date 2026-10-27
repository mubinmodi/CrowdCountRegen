import numpy as np
import supervision as sv

try:
    from ultralytics import YOLO
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "The 'ultralytics' detector needs the yolo extra: uv sync --extra yolo"
    ) from e

PERSON_CLASS_ID = 0  # COCO index used by Ultralytics models


class UltralyticsDetector:
    """Ultralytics YOLO (AGPL-3.0). `model` is any Ultralytics weights name or path."""

    name = "ultralytics"

    def __init__(self, model: str, confidence: float, device: str | None, imgsz: int = 640) -> None:
        self._model = YOLO(model)
        self._confidence = confidence
        self._device = device
        self._imgsz = imgsz

    def detect(self, frame_bgr: np.ndarray) -> sv.Detections:
        result = self._model.predict(
            frame_bgr,
            classes=[PERSON_CLASS_ID],
            conf=self._confidence,
            device=self._device,
            imgsz=self._imgsz,
            verbose=False,
        )[0]
        return sv.Detections.from_ultralytics(result)
