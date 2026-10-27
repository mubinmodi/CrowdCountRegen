"""One thread per camera: read frames -> detect -> track -> count in zone -> annotate."""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self

import cv2
import numpy as np
import supervision as sv
from trackers import ByteTrackTracker

from app.config import Settings
from app.vision.alerts import Mode
from app.vision.counter import Polygon, ZoneCounter
from app.vision.detectors import Detector
from app.vision.sources import BrowserHub, SourceSpec
from app.vision.sources.base import StreamInfo
from app.vision.sources.reader import FrameReader
from app.vision.stats import MinuteAggregator

log = logging.getLogger(__name__)

_IN_ZONE = sv.Color.from_hex("#3ee08f")
_OUT_OF_ZONE = sv.Color.from_hex("#8b97a6")
_ZONE = sv.Color.from_hex("#ff8a3d")
# Danger zones: people inside are the alarm, so they are red and everyone else is neutral.
_HAZARD = sv.Color.from_hex("#ff3b3b")
_HAZARD_STRIPE = (0, 200, 255)  # BGR safety yellow
_SMALL_WIDTH = 480  # second, smaller stream for the live wall's tiles


@dataclass(frozen=True)
class CameraConfig:
    """Everything that shapes frame processing. Changing any of it restarts the worker, which
    resets tracking, so settings that only interpret the counts (like the alert threshold)
    belong elsewhere."""

    camera_id: int
    source: SourceSpec
    zone: Polygon | None
    mode: Mode = "occupancy"  # only changes how the zone and people are drawn


@dataclass(frozen=True)
class CameraSnapshot:
    """A camera's live status, read at one moment."""

    camera_id: int
    state: str  # starting | connecting | running | waiting | error | stopped
    error: str | None
    error_code: str | None
    hint: str | None
    occupancy: int
    unique_entries: int
    fps: float
    stream: StreamInfo | None
    reconnects: int
    publisher_connected: bool | None = None  # browser cameras only
    alert_limit: int | None = None  # most people allowed in the zone; None = no alert
    over_limit: bool = False  # running, and occupancy is above alert_limit

    @classmethod
    def stopped(cls, camera_id: int) -> Self:
        return cls(camera_id, "stopped", None, None, None, 0, 0, 0.0, None, 0)


class CameraWorker(threading.Thread):
    def __init__(
        self, config: CameraConfig, detector: Detector, settings: Settings, hub: BrowserHub
    ) -> None:
        super().__init__(daemon=True, name=f"camera:{config.camera_id}")
        self.config = config
        self._detector = detector
        self._settings = settings
        self._stop_event = threading.Event()
        self._reader = FrameReader(config.camera_id, config.source, settings, hub)
        self._tracker = ByteTrackTracker(
            frame_rate=settings.max_fps,
            track_activation_threshold=settings.confidence,
        )
        self._counter = ZoneCounter(config.zone)
        self.stats = MinuteAggregator()

        self._out_lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._jpeg_small: bytes | None = None  # for grid tiles: a fraction of the bandwidth
        self._raw: np.ndarray | None = None
        self.jpeg_seq = 0
        self._occupancy = 0
        self._unique_entries = 0

        self._fps = 0.0
        self._error: str | None = None  # processing failure; source failures live on the reader

    # -- public, thread-safe accessors ------------------------------------------------------

    def snapshot(self) -> CameraSnapshot:
        camera_id = self.config.camera_id
        with self._out_lock:
            has_frame = self._jpeg is not None
            occupancy, unique_entries = self._occupancy, self._unique_entries
        reader_state, source_error = self._reader.health
        processing_error = self._error

        if self._stop_event.is_set():
            state = "stopped"
        elif processing_error:
            state = "error"
        elif reader_state == "running" and not has_frame:
            state = "starting"
        else:
            state = reader_state

        if processing_error:
            error, error_code, hint = processing_error, "error", None
        elif source_error:
            error, error_code, hint = source_error.message, source_error.code, source_error.hint
        else:
            error = error_code = hint = None

        return CameraSnapshot(
            camera_id=camera_id,
            state=state,
            error=error,
            error_code=error_code,
            hint=hint,
            occupancy=occupancy,
            unique_entries=unique_entries,
            fps=round(self._fps, 1),
            stream=self._reader.info,
            reconnects=self._reader.reconnects,
        )

    def latest_jpeg(self, small: bool = False) -> tuple[int, bytes | None]:
        with self._out_lock:
            return self.jpeg_seq, self._jpeg_small if small else self._jpeg

    def snapshot_jpeg(self) -> bytes | None:
        """Latest frame without annotations, used by the zone editor."""
        with self._out_lock:
            raw = self._raw
        if raw is None:
            return None
        ok, buf = cv2.imencode(".jpg", raw, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return buf.tobytes() if ok else None

    def stop(self) -> None:
        self._stop_event.set()
        self._reader.stop()

    # -- thread body ------------------------------------------------------------------------

    def run(self) -> None:
        self._reader.start()
        min_interval = 1.0 / self._settings.max_fps
        last_seq = 0
        period_start = time.monotonic()
        while not self._stop_event.is_set():
            seq, frame = self._reader.latest(last_seq, timeout=1.0)
            if frame is None or seq == last_seq:
                self._fps = 0.0
                continue
            last_seq = seq
            try:
                self._process(frame)
                self._error = None
            except Exception as e:  # keep the camera alive across transient model errors
                log.exception("camera %s: frame processing failed", self.config.camera_id)
                self._error = f"Processing failed: {e}"
                self._stop_event.wait(1.0)

            # Cap the processing rate at max_fps, then track the achieved rate.
            spent = time.monotonic() - period_start
            if spent < min_interval:
                self._stop_event.wait(min_interval - spent)
            now = time.monotonic()
            self._fps = 0.9 * self._fps + 0.1 / (now - period_start)
            period_start = now
        self._reader.join(timeout=5)

    def _process(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        target_w = self._settings.frame_width
        if w > target_w:
            frame = cv2.resize(frame, (target_w, round(h * target_w / w)))
            h, w = frame.shape[:2]

        detections = self._detector.detect(frame)
        detections = self._tracker.update(detections)
        result = self._counter.update(detections, (w, h))

        self.stats.record(datetime.now(UTC), result.occupancy, result.new_entries)

        annotated = self._annotate(frame, detections, result.in_zone)
        ok, buf = cv2.imencode(
            ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, self._settings.jpeg_quality]
        )
        ok_small, buf_small = False, None
        if w > _SMALL_WIDTH:  # smaller sources just reuse the full frame
            small_size = (_SMALL_WIDTH, round(h * _SMALL_WIDTH / w))
            small = cv2.resize(annotated, small_size, interpolation=cv2.INTER_AREA)
            ok_small, buf_small = cv2.imencode(
                ".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, self._settings.jpeg_quality]
            )
        with self._out_lock:
            self._occupancy = result.occupancy
            self._unique_entries = self._counter.unique_entries
            if ok:
                self._jpeg = buf.tobytes()
                self._jpeg_small = (
                    buf_small.tobytes() if ok_small and buf_small is not None else self._jpeg
                )
                self._raw = frame
                self.jpeg_seq += 1

    def _annotate(
        self, frame: np.ndarray, detections: sv.Detections, in_zone: np.ndarray
    ) -> np.ndarray:
        out = frame.copy()
        danger = self.config.mode == "danger_zone"
        polygon = self._counter.pixel_polygon((frame.shape[1], frame.shape[0]))
        if polygon is not None and danger:
            out = _draw_hazard_zone(out, polygon, alarm=bool(in_zone.any()))
        elif polygon is not None:
            out = sv.draw_polygon(out, polygon, color=_ZONE, thickness=2)
        if len(detections):
            thickness = sv.calculate_optimal_line_thickness((frame.shape[1], frame.shape[0]))
            inside = _HAZARD if danger else _IN_ZONE
            for mask, color in ((~in_zone, _OUT_OF_ZONE), (in_zone, inside)):
                if mask.any():
                    out = sv.BoxAnnotator(color=color, thickness=thickness).annotate(
                        out, detections[mask]
                    )

        # Counts are shown by the UI; the stream only carries a CCTV-style timestamp.
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        (tw, th), _ = cv2.getTextSize(stamp, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        h = frame.shape[0]
        cv2.rectangle(out, (8, h - th - 18), (8 + tw + 12, h - 8), (10, 7, 5), -1)
        cv2.putText(
            out, stamp, (14, h - 13), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
            (238, 230, 223), 1, cv2.LINE_AA,
        )  # fmt: skip
        return out


def _draw_hazard_zone(frame: np.ndarray, polygon: np.ndarray, alarm: bool) -> np.ndarray:
    """A red-tinted zone with a yellow-and-black striped border, like site barrier tape."""
    tint = frame.copy()
    cv2.fillPoly(tint, [polygon.astype(np.int32)], _HAZARD.as_bgr())
    out = cv2.addWeighted(tint, 0.32 if alarm else 0.16, frame, 0.68 if alarm else 0.84, 0)
    pts = polygon.astype(np.int32)
    thickness = max(3, frame.shape[1] // 240)
    cv2.polylines(out, [pts], True, (20, 20, 20), thickness + 2, cv2.LINE_AA)
    dash = thickness * 4
    for a, b in zip(pts, np.roll(pts, -1, axis=0), strict=True):
        length = float(np.hypot(*(b - a)))
        for start in range(0, int(length), dash * 2):
            p = a + (b - a) * (start / length)
            q = a + (b - a) * (min(start + dash, length) / length)
            cv2.line(out, tuple(p.astype(int)), tuple(q.astype(int)), _HAZARD_STRIPE, thickness)
    top = pts[pts[:, 1].argmin()]
    label = "DANGER ZONE"
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    x = int(np.clip(top[0] - tw // 2, 4, frame.shape[1] - tw - 16))
    y = int(np.clip(top[1] - 10, th + 10, frame.shape[0] - 4))
    cv2.rectangle(out, (x - 6, y - th - 6), (x + tw + 6, y + 6), _HAZARD_STRIPE, -1)
    cv2.putText(out, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return out
