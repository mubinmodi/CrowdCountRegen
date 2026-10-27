"""Background frame reader that always holds the newest frame from a camera.

Reading in a dedicated thread keeps live streams from building up latency: if inference is
slower than the camera, stale frames are dropped instead of queued. Failures reconnect with
exponential backoff, and the last error is kept (with a code and hint) for the UI.
"""

import logging
import threading
import time

import numpy as np

from app.config import Settings
from app.vision.sources import BrowserHub, open_source
from app.vision.sources.base import StreamInfo
from app.vision.sources.errors import SourceError, classify
from app.vision.sources.spec import SourceSpec

log = logging.getLogger(__name__)


class FrameReader(threading.Thread):
    def __init__(
        self, camera_id: int, spec: SourceSpec, settings: Settings, hub: BrowserHub
    ) -> None:
        super().__init__(daemon=True, name=f"reader:{camera_id}")
        self._camera_id = camera_id
        self._spec = spec
        self._settings = settings
        self._hub = hub
        self._stop_event = threading.Event()
        self._cond = threading.Condition()
        self._frame: np.ndarray | None = None
        self._seq = 0
        self.state = "connecting"  # connecting | running | waiting | error | stopped
        self.error: SourceError | None = None
        self.info: StreamInfo | None = None
        self.reconnects = 0

    def stop(self) -> None:
        self._stop_event.set()
        with self._cond:
            self._cond.notify_all()

    def latest(self, after_seq: int, timeout: float) -> tuple[int, np.ndarray | None]:
        """Waits up to `timeout` for a frame newer than `after_seq`."""
        with self._cond:
            self._cond.wait_for(
                lambda: self._seq > after_seq or self._stop_event.is_set(), timeout=timeout
            )
            return self._seq, self._frame

    def _fail(self, error: SourceError, backoff: float) -> float:
        """Records the error, waits, and returns the next backoff delay."""
        if error.code == "waiting":
            # Not a fault: poll again soon, without growing the delay.
            self.state, self.error = "waiting", error
            self._stop_event.wait(0.5)
            return backoff
        self.state, self.error = "error", error
        log.info(
            "camera %s: %s (%s); retry in %.0fs",
            self._camera_id,
            error.message,
            error.code,
            backoff,
        )
        self._stop_event.wait(backoff)
        return min(backoff * 2, self._settings.reconnect_max_delay_s)

    def run(self) -> None:
        base_delay = self._settings.reconnect_delay_s
        backoff = base_delay
        while not self._stop_event.is_set():
            try:
                source = open_source(self._spec, self._settings, self._hub, self._camera_id)
            except SourceError as e:
                backoff = self._fail(e, backoff)
                continue

            self.info = source.info
            frame_interval = 1.0 / (source.info.fps or 25.0) if not source.info.live else 0.0
            next_at = time.monotonic()
            try:
                while not self._stop_event.is_set():
                    frame = source.read()
                    if self.state != "running":
                        self.state, self.error, backoff = "running", None, base_delay
                    with self._cond:
                        self._frame = frame
                        self._seq += 1
                        self._cond.notify_all()
                    # Files play back at their native rate so they behave like a camera.
                    if frame_interval:
                        next_at += frame_interval
                        if (delay := next_at - time.monotonic()) > 0:
                            self._stop_event.wait(delay)
                        else:
                            next_at = time.monotonic()
            except Exception as e:  # SourceError, or anything unexpected from a decoder
                source.close()
                if not self._stop_event.is_set():
                    self.reconnects += 1
                    backoff = self._fail(classify(e), backoff)
                continue
            source.close()
        self.state = "stopped"
