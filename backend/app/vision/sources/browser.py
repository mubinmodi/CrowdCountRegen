"""Frames pushed by a browser (phone or laptop camera) over a WebSocket.

The publish endpoint writes JPEG-decoded frames into a per-camera slot in the hub; the
camera's reader consumes them like any other source.
"""

import threading
import time

import numpy as np

from app.vision.sources.base import StreamInfo
from app.vision.sources.errors import SourceError


class BrowserSlot:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._frame: np.ndarray | None = None
        self._seq = 0
        self.publisher_generation = 0  # bumped when a new publisher takes over
        self.publisher_connected = False
        self.publisher_info: str | None = None
        self.last_frame_at = 0.0

    def push(self, frame: np.ndarray) -> None:
        with self._cond:
            self._frame = frame
            self._seq += 1
            self.last_frame_at = time.monotonic()
            self._cond.notify_all()

    def wait(self, after_seq: int, timeout: float) -> tuple[int, np.ndarray | None]:
        with self._cond:
            self._cond.wait_for(lambda: self._seq > after_seq, timeout=timeout)
            return self._seq, self._frame

    def attach(self, info: str | None) -> int:
        """Registers a new publisher, displacing any current one. Returns its generation."""
        with self._cond:
            self.publisher_generation += 1
            self.publisher_connected = True
            self.publisher_info = info
            return self.publisher_generation

    def detach(self, generation: int) -> None:
        with self._cond:
            if generation == self.publisher_generation:
                self.publisher_connected = False
                self.publisher_info = None


class BrowserHub:
    def __init__(self) -> None:
        self._slots: dict[int, BrowserSlot] = {}
        self._lock = threading.Lock()

    def slot(self, camera_id: int) -> BrowserSlot:
        with self._lock:
            return self._slots.setdefault(camera_id, BrowserSlot())

    def discard(self, camera_id: int) -> None:
        with self._lock:
            self._slots.pop(camera_id, None)


class BrowserSource:
    def __init__(self, slot: BrowserSlot, read_timeout: float) -> None:
        self._slot = slot
        self._timeout = read_timeout
        # Report "waiting" quickly when nobody is publishing; the reader polls again soon.
        self._seq, frame = slot.wait(0, timeout=1.0)
        if frame is None or time.monotonic() - slot.last_frame_at > read_timeout:
            raise SourceError("waiting", "Waiting for a browser to start publishing")
        self._pending: np.ndarray | None = frame
        self.info = StreamInfo(
            width=frame.shape[1], height=frame.shape[0], fps=None, codec="jpeg", live=True
        )

    def read(self) -> np.ndarray:
        if self._pending is not None:
            frame, self._pending = self._pending, None
            return frame
        seq, frame = self._slot.wait(self._seq, timeout=self._timeout)
        if seq == self._seq or frame is None:
            raise SourceError("waiting", "The publishing browser stopped sending frames")
        self._seq = seq
        return frame

    def close(self) -> None:
        pass
