"""Owns all camera workers, the shared detector, and periodic persistence of counts."""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.crypto import decrypt
from app.db import Camera, CountSample
from app.vision.detectors import Detector, build_detector
from app.vision.sources import BrowserHub, SourceSpec
from app.vision.stats import MinuteBucket
from app.vision.worker import CameraConfig, CameraWorker

log = logging.getLogger(__name__)


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def spec_from_camera(camera: Camera) -> SourceSpec:
    return SourceSpec(
        kind=camera.kind,  # type: ignore[arg-type]
        url=camera.source,
        username=camera.username,
        password=decrypt(camera.password_enc) if camera.password_enc else None,
        options=dict(camera.options or {}),
    )


def config_from_camera(camera: Camera) -> CameraConfig:
    zone = [(float(x), float(y)) for x, y in camera.zone] if camera.zone else None
    return CameraConfig(camera.id, spec_from_camera(camera), zone, camera.threshold)


class CameraManager:
    def __init__(
        self,
        settings: Settings,
        session_factory: Callable[[], Session],
        detector_factory: Callable[[Settings], Detector] = build_detector,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._detector_factory = detector_factory
        self._detector: Detector | None = None
        self._workers: dict[int, CameraWorker] = {}
        self.browser_hub = BrowserHub()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._flusher = threading.Thread(target=self._flush_loop, daemon=True, name="flusher")

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def detector(self) -> Detector:
        # Loaded lazily so the API starts instantly even when model weights must download.
        with self._lock:
            if self._detector is None:
                self._detector = self._detector_factory(self._settings)
                log.info("Loaded detector: %s", self._detector.name)
            return self._detector

    def start(self) -> None:
        if not self._settings.start_workers:
            return
        with self._session_factory() as db:
            cameras = db.scalars(select(Camera)).all()
        for camera in cameras:
            self.upsert(camera)
        self._flusher.start()

    def shutdown(self) -> None:
        self._stop_event.set()
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            self._stop_worker(worker)

    def upsert(self, camera: Camera) -> None:
        """Starts a worker for the camera, replacing any existing one if its config changed."""
        if not self._settings.start_workers:
            return
        config = config_from_camera(camera)
        with self._lock:
            existing = self._workers.get(camera.id)
            if existing is not None and existing.config == config:
                return
            worker = CameraWorker(config, self.detector, self._settings, self.browser_hub)
            self._workers[camera.id] = worker
        if existing is not None:
            self._stop_worker(existing)
        worker.start()

    def remove(self, camera_id: int, persist: bool = True) -> None:
        with self._lock:
            worker = self._workers.pop(camera_id, None)
        if worker is not None:
            self._stop_worker(worker, persist=persist)
        self.browser_hub.discard(camera_id)

    def get(self, camera_id: int) -> CameraWorker | None:
        return self._workers.get(camera_id)

    def _stop_worker(self, worker: CameraWorker, persist: bool = True) -> None:
        worker.stop()
        worker.join(timeout=10)
        if persist:
            self._persist(worker.config.camera_id, worker.stats.drain(include_current=True))

    def _flush_loop(self) -> None:
        while not self._stop_event.wait(self._settings.flush_interval_s):
            self.flush()

    def flush(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
        for worker in workers:
            self._persist(worker.config.camera_id, worker.stats.drain())

    def _persist(self, camera_id: int, buckets: list[MinuteBucket]) -> None:
        if not buckets:
            return
        try:
            with self._session_factory() as db:
                if db.get(Camera, camera_id) is None:  # camera was deleted meanwhile
                    return
                existing = {
                    _as_utc(row.minute): row
                    for row in db.scalars(
                        select(CountSample).where(
                            CountSample.camera_id == camera_id,
                            CountSample.minute.in_([b.minute for b in buckets]),
                        )
                    )
                }
                for b in buckets:
                    row = existing.get(b.minute)
                    if row is None:
                        db.add(
                            CountSample(
                                camera_id=camera_id,
                                minute=b.minute,
                                avg_occupancy=round(b.avg, 3),
                                peak_occupancy=b.peak,
                                entries=b.entries,
                                frames=b.frames,
                            )
                        )
                        continue
                    # The same minute can be written twice when a worker restarts mid-minute.
                    frames = row.frames + b.frames
                    row.avg_occupancy = round(
                        (row.avg_occupancy * row.frames + b.occupancy_sum) / frames, 3
                    )
                    row.peak_occupancy = max(row.peak_occupancy, b.peak)
                    row.entries += b.entries
                    row.frames = frames
                db.commit()
        except Exception:
            log.exception("Failed to persist counts for camera %s", camera_id)
