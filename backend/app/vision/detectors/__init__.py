"""Person detectors. Each backend returns `sv.Detections` containing only people."""

import threading
import time
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import supervision as sv

from app.config import Settings


class Detector(Protocol):
    name: str

    def detect(self, frame_bgr: np.ndarray) -> sv.Detections: ...


@dataclass(frozen=True)
class DetectorStats:
    inferences: int
    inference_ms: float  # mean time inside the model
    lock_wait_ms: float  # mean time spent queuing for it: the saturation signal


class LockedDetector:
    """Shares one model across camera workers; inference is serialized with a lock.

    Neither backend guarantees thread-safe inference, and on a single GPU serializing
    is about as fast as running in parallel anyway. Lock wait time is the capacity signal:
    once it rivals the inference time, cameras are queuing for the accelerator.
    """

    def __init__(self, inner: Detector) -> None:
        self._inner = inner
        self._lock = threading.Lock()
        self.name = inner.name
        self._stats_lock = threading.Lock()
        self._count = 0
        self._busy_s = 0.0
        self._wait_s = 0.0

    def detect(self, frame_bgr: np.ndarray) -> sv.Detections:
        queued = time.perf_counter()
        with self._lock:
            started = time.perf_counter()
            result = self._inner.detect(frame_bgr)
        done = time.perf_counter()
        with self._stats_lock:
            self._count += 1
            self._wait_s += started - queued
            self._busy_s += done - started
        return result

    def drain_stats(self) -> DetectorStats:
        """Stats since the last call."""
        with self._stats_lock:
            n, busy, wait = self._count, self._busy_s, self._wait_s
            self._count, self._busy_s, self._wait_s = 0, 0.0, 0.0
        return DetectorStats(n, busy * 1000 / n if n else 0.0, wait * 1000 / n if n else 0.0)


def build_detector(settings: Settings) -> Detector:
    match settings.detector:
        case "ultralytics":
            from app.vision.detectors.ultralytics import UltralyticsDetector

            inner: Detector = UltralyticsDetector(
                settings.detector_model or "models/yolo26n.pt",
                settings.confidence,
                settings.device,
                settings.detector_imgsz,
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
