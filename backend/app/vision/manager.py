"""Owns all camera workers, the shared detector, periodic persistence of counts, and the
incident monitor that turns alerts into a log."""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.crypto import decrypt
from app.db import Camera, CountSample, Incident
from app.vision.alerts import IncidentEvent, IncidentTracker, alert_limit
from app.vision.detectors import Detector, DetectorStats, build_detector
from app.vision.sources import BrowserHub, SourceSpec
from app.vision.stats import MinuteBucket
from app.vision.worker import CameraConfig, CameraSnapshot, CameraWorker

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
    return CameraConfig(camera.id, spec_from_camera(camera), zone, camera.mode)  # type: ignore[arg-type]


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
        self._limits: dict[int, int | None] = {}  # alert limits; not part of CameraConfig
        self._trackers: dict[int, IncidentTracker] = {}
        # camera id -> (open Incident id, peak written so far)
        self._open_incidents: dict[int, tuple[int, int]] = {}
        # Incident id -> (ended_at, peak) for closes that failed to write; retried each tick,
        # so a database hiccup can't leave an incident open forever.
        self._unwritten_closes: dict[int, tuple[datetime, int | None]] = {}
        self.browser_hub = BrowserHub()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._flusher = threading.Thread(target=self._flush_loop, daemon=True, name="flusher")
        self._monitor = threading.Thread(target=self._monitor_loop, daemon=True, name="incidents")

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

    def detector_stats(self) -> DetectorStats | None:
        """Inference stats since the last call; None until the model has been loaded."""
        drain = getattr(self._detector, "drain_stats", None)
        return drain() if drain is not None else None

    @property
    def camera_ids(self) -> list[int]:
        with self._lock:
            return list(self._workers)

    @property
    def open_incidents(self) -> int:
        with self._lock:
            return len(self._open_incidents)

    def start(self) -> None:
        if not self._settings.start_workers:
            return
        with self._session_factory() as db:
            cameras = db.scalars(select(Camera)).all()
        self._close_dangling_incidents()
        for camera in cameras:
            self.upsert(camera)
        self._flusher.start()
        self._monitor.start()

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._monitor.is_alive():
            self._monitor.join(timeout=5)
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
            self._limits.clear()
            open_incidents = dict(self._open_incidents)
        for camera_id in open_incidents:
            self._try_close_incident(camera_id)
        for worker in workers:
            self._stop_worker(worker)

    def upsert(self, camera: Camera) -> None:
        """Starts a worker for the camera, replacing any existing one if its config changed.

        The alert limit applies immediately and never restarts the worker.
        """
        if not self._settings.start_workers:
            return
        config = config_from_camera(camera)
        with self._lock:
            self._limits[camera.id] = alert_limit(camera.mode, camera.threshold)
            existing = self._workers.get(camera.id)
            if existing is not None and existing.config == config:
                return
            mode_changed = existing is not None and existing.config.mode != config.mode
            if mode_changed:
                self._trackers.pop(camera.id, None)  # debounce depends on the mode
            worker = CameraWorker(config, self.detector, self._settings, self.browser_hub)
            self._workers[camera.id] = worker
        if existing is not None:
            if mode_changed:
                self._try_close_incident(camera.id)
            self._stop_worker(existing)
        worker.start()

    def remove(self, camera_id: int, persist: bool = True) -> None:
        with self._lock:
            worker = self._workers.pop(camera_id, None)
            self._limits.pop(camera_id, None)
            self._trackers.pop(camera_id, None)
            self._open_incidents.pop(camera_id, None)  # its rows go with the camera
        if worker is not None:
            self._stop_worker(worker, persist=persist)
        self.browser_hub.discard(camera_id)

    def get(self, camera_id: int) -> CameraWorker | None:
        return self._workers.get(camera_id)

    def status(self, camera_id: int) -> CameraSnapshot:
        """Everything the UI shows about a camera right now, including whether it is over its
        alert limit. A camera without a worker reports as stopped.

        Only a running camera can alert: after a disconnect its last count is stale.
        """
        with self._lock:
            worker = self._workers.get(camera_id)
            limit = self._limits.get(camera_id)
        if worker is None:
            return CameraSnapshot.stopped(camera_id)
        snapshot = worker.snapshot()
        publisher = None
        if worker.config.source.kind == "browser":
            publisher = self.browser_hub.slot(camera_id).publisher_connected
        return replace(
            snapshot,
            publisher_connected=publisher,
            alert_limit=limit,
            over_limit=(
                limit is not None and snapshot.state == "running" and snapshot.occupancy > limit
            ),
        )

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
        """Writes minute buckets, merging into rows that already exist for the same minute.

        Read-then-insert can race: a worker being replaced (request thread) and the flusher
        can write the same camera and minute at once, and the second insert then hits the
        (camera_id, minute) unique key. Rolling back and merging again resolves it, because
        the other writer's row is now there to merge into.
        """
        if not buckets:
            return
        for attempt in (1, 2):
            try:
                with self._session_factory() as db:
                    if db.get(Camera, camera_id) is None:  # camera was deleted meanwhile
                        return
                    self._merge(db, camera_id, buckets)
                    db.commit()
                return
            except IntegrityError:
                if attempt == 2:
                    log.exception("Failed to persist counts for camera %s", camera_id)
            except Exception:
                log.exception("Failed to persist counts for camera %s", camera_id)
                return

    @staticmethod
    def _merge(db: Session, camera_id: int, buckets: list[MinuteBucket]) -> None:
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

    # -- incidents --------------------------------------------------------------------------

    def _monitor_loop(self) -> None:
        while not self._stop_event.wait(0.5):
            self.check_incidents(time.monotonic())

    def check_incidents(self, now: float) -> None:
        """Samples every camera's alert flag once and records incidents opening or closing.

        Each camera is handled on its own: a failure (say, SQLite briefly locked, or a dropped
        Postgres connection) is logged and retried on the next tick, and never stops the other
        cameras or the monitor thread itself.
        """
        with self._lock:
            camera_ids = list(self._workers)
            retries = list(self._unwritten_closes.items())
        for incident_id, (at, peak) in retries:
            try:
                self._write_close(incident_id, at, peak)
            except Exception:
                log.exception("Closing incident %s failed again; will retry", incident_id)
        for camera_id in camera_ids:
            try:
                self._check_camera(camera_id, now)
            except Exception:
                log.exception("Incident check failed for camera %s", camera_id)

    def _check_camera(self, camera_id: int, now: float) -> None:
        status = self.status(camera_id)
        worker = self.get(camera_id)
        if worker is None:
            return
        with self._lock:
            tracker = self._trackers.get(camera_id)
            if tracker is None:
                close_after = (
                    self._settings.incident_close_after_s
                    if worker.config.mode == "danger_zone"
                    else self._settings.occupancy_incident_close_after_s
                )
                tracker = IncidentTracker(self._settings.incident_open_after_s, close_after)
                self._trackers[camera_id] = tracker
        event = tracker.update(now, status.over_limit, status.occupancy)
        if event is not None:
            self._record(camera_id, event, now, status.alert_limit or 0)
        elif tracker.is_open:
            self._update_peak(camera_id, tracker.peak)

    def _record(self, camera_id: int, event: IncidentEvent, now: float, limit: int) -> None:
        at = datetime.now(UTC) - timedelta(seconds=now - event.at)
        if event.kind == "closed":
            self._close_incident(camera_id, at, event.peak)
            return
        worker = self.get(camera_id)
        snapshot = worker.latest_jpeg()[1] if worker else None
        keep = self._settings.incidents_kept_per_camera
        try:
            with self._session_factory() as db:
                incident = Incident(
                    camera_id=camera_id, started_at=at, peak=event.peak, limit=limit,
                    snapshot=snapshot,
                )  # fmt: skip
                db.add(incident)
                db.flush()
                newest = (
                    select(Incident.id)
                    .where(Incident.camera_id == camera_id)
                    .order_by(Incident.started_at.desc())
                    .limit(keep)
                )
                db.execute(
                    delete(Incident).where(
                        Incident.camera_id == camera_id, Incident.id.not_in(newest)
                    )
                )
                db.commit()
                with self._lock:
                    self._open_incidents[camera_id] = (incident.id, event.peak)
        except Exception:
            log.exception("Failed to record an incident for camera %s", camera_id)

    def _update_peak(self, camera_id: int, peak: int) -> None:
        with self._lock:
            incident_id, written = self._open_incidents.get(camera_id, (None, 0))
        if incident_id is None or peak <= written:
            return
        with self._session_factory() as db:
            db.execute(update(Incident).where(Incident.id == incident_id).values(peak=peak))
            db.commit()
        # Only once it's written, so a failed write is tried again on the next tick.
        with self._lock:
            if self._open_incidents.get(camera_id, (None, 0))[0] == incident_id:
                self._open_incidents[camera_id] = (incident_id, peak)

    def _close_incident(self, camera_id: int, at: datetime, peak: int | None = None) -> None:
        with self._lock:
            incident_id, _ = self._open_incidents.pop(camera_id, (None, 0))
            if incident_id is None:
                return
            # Queued first: if the write below fails, the next tick retries it.
            self._unwritten_closes[incident_id] = (at, peak)
        self._write_close(incident_id, at, peak)

    def _try_close_incident(self, camera_id: int) -> None:
        """Closes a camera's open incident now, outside the monitor (a mode change, shutdown).
        A failed write is logged, not raised: it's queued and the monitor retries it."""
        try:
            self._close_incident(camera_id, datetime.now(UTC))
        except Exception:
            log.exception("Closing the incident of camera %s failed; will retry", camera_id)

    def _write_close(self, incident_id: int, at: datetime, peak: int | None) -> None:
        values: dict = {"ended_at": at}
        if peak is not None:
            values["peak"] = peak
        with self._session_factory() as db:
            db.execute(update(Incident).where(Incident.id == incident_id).values(**values))
            db.commit()
        with self._lock:
            self._unwritten_closes.pop(incident_id, None)

    def _close_dangling_incidents(self) -> None:
        """Incidents still open from a previous run ended when it stopped; the exact time is
        unknown, so they end where they started rather than claim a made-up duration."""
        with self._session_factory() as db:
            db.execute(
                update(Incident)
                .where(Incident.ended_at.is_(None))
                .values(ended_at=Incident.started_at)
            )
            db.commit()
