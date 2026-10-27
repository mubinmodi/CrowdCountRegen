"""Cameras attached to the server itself (USB/built-in), via OpenCV's native backends."""

import cv2
import numpy as np

from app.vision.sources.base import StreamInfo
from app.vision.sources.errors import SourceError
from app.vision.sources.spec import SourceSpec


class WebcamSource:
    def __init__(self, spec: SourceSpec) -> None:
        device: int | str = int(spec.url) if spec.url.isdigit() else spec.url
        self._cap = cv2.VideoCapture(device)
        if not self._cap.isOpened():
            self._cap.release()
            raise SourceError(
                "unreachable", f"Webcam {spec.url} not found, in use, or camera permission denied"
            )
        if width := spec.options.get("width"):
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(width))
        ok, first = self._cap.read()
        if not ok:
            self._cap.release()
            raise SourceError("invalid", f"Webcam {spec.url} opened but returned no frames")
        self._pending: np.ndarray | None = first
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        self.info = StreamInfo(
            width=first.shape[1], height=first.shape[0], fps=fps or None, codec="raw", live=True
        )

    def read(self) -> np.ndarray:
        if self._pending is not None:
            frame, self._pending = self._pending, None
            return frame
        ok, frame = self._cap.read()
        if not ok:
            raise SourceError("ended", "Webcam stopped delivering frames")
        return frame

    def close(self) -> None:
        self._cap.release()
