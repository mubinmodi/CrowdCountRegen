"""Person detectors. Each backend returns `sv.Detections` containing only people."""

import threading
from typing import Protocol

import numpy as np
import supervision as sv

from app.config import Settings


class Detector(Protocol):
    name: str

    def detect(self, frame_bgr: np.ndarray) -> sv.Detections: ...


class LockedDetector:
    """Shares one model across camera workers; inference is serialized with a lock.

    Neither backend guarantees thread-safe inference, and on a single GPU serializing
    is about as fast as running in parallel anyway.
    """

    def __init__(self, inner: Detector) -> None:
        self._inner = inner
        self._lock = threading.Lock()
        self.name = inner.name

    def detect(self, frame_bgr: np.ndarray) -> sv.Detections:
        with self._lock:
            return self._inner.detect(frame_bgr)


def build_detector(settings: Settings) -> Detector:
    match settings.detector:
        case "ultralytics":
            from app.vision.detectors.ultralytics import UltralyticsDetector

            inner: Detector = UltralyticsDetector(
                settings.detector_model or "models/yolo26n.pt", settings.confidence, settings.device
            )
        case "rfdetr":
            from app.vision.detectors.rfdetr import RFDETRDetector

            inner = RFDETRDetector(
                settings.detector_model or "nano", settings.confidence, settings.device
            )
        case "fake":
            from app.vision.detectors.fake import FakeDetector

            inner = FakeDetector()
    return LockedDetector(inner)
