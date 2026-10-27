"""Publishes per-camera and fleet metrics as CloudWatch Embedded Metric Format log lines."""

import json
import logging
import sys
import threading
import time
from typing import TextIO

from app.viewers import VideoSlots
from app.vision.manager import CameraManager

log = logging.getLogger(__name__)

NAMESPACE = "CrowdCounting"
# A camera is stalled when it should be producing frames and isn't. A source that stops
# sending trips the reader's read timeout and moves to "error", so state alone is enough;
# "waiting" (a phone camera nobody is publishing to) and "starting" are normal.
_STALLED_STATES = {"error", "connecting"}


def _emf(timestamp_ms: int, dimensions: list[str], metrics: dict[str, tuple[float, str]],
         properties: dict) -> dict:  # fmt: skip
    return {
        "_aws": {
            "Timestamp": timestamp_ms,
            "CloudWatchMetrics": [
                {
                    "Namespace": NAMESPACE,
                    "Dimensions": [dimensions],
                    "Metrics": [{"Name": n, "Unit": unit} for n, (_, unit) in metrics.items()],
                }
            ],
        },
        **properties,
        **{name: value for name, (value, _) in metrics.items()},
    }


class MetricsCollector:
    """Builds one EMF record per camera and one for the fleet. Counters are reported as the
    change since the previous call, so CloudWatch sums are meaningful."""

    def __init__(self, manager: CameraManager, slots: VideoSlots) -> None:
        self._manager = manager
        self._slots = slots
        self._reconnects: dict[int, int] = {}

    def collect(self, now_ms: int | None = None) -> list[dict]:
        now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        records = []
        running = stalled = alerting = 0
        for camera_id in self._manager.camera_ids:
            s = self._manager.status(camera_id)
            running += s.state == "running"
            stalled += s.state in _STALLED_STATES
            alerting += s.over_limit
            reconnects = s.reconnects - self._reconnects.get(camera_id, s.reconnects)
            self._reconnects[camera_id] = s.reconnects
            records.append(
                _emf(
                    now_ms,
                    ["CameraId"],
                    {
                        "FPS": (s.fps, "Count/Second"),
                        "Occupancy": (s.occupancy, "Count"),
                        "Alerting": (int(s.over_limit), "Count"),
                        "Reconnects": (max(reconnects, 0), "Count"),
                    },
                    {"CameraId": str(camera_id), "State": s.state},
                )
            )
        fleet: dict[str, tuple[float, str]] = {
            "Cameras": (len(records), "Count"),
            "CamerasRunning": (running, "Count"),
            "CamerasStalled": (stalled, "Count"),
            "CamerasAlerting": (alerting, "Count"),
            "IncidentsOpen": (self._manager.open_incidents, "Count"),
            "VideoViewers": (self._slots.in_use, "Count"),
        }
        if (stats := self._manager.detector_stats()) is not None:
            fleet["Inferences"] = (stats.inferences, "Count")
            fleet["InferenceMs"] = (round(stats.inference_ms, 2), "Milliseconds")
            fleet["LockWaitMs"] = (round(stats.lock_wait_ms, 2), "Milliseconds")
        records.append(_emf(now_ms, [], fleet, {}))
        return records


class MetricsEmitter(threading.Thread):
    def __init__(self, collector: MetricsCollector, interval_s: float,
                 out: TextIO = sys.stdout) -> None:  # fmt: skip
        super().__init__(daemon=True, name="metrics")
        self._collector = collector
        self._interval = interval_s
        self._out = out
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.wait(self._interval):
            try:
                lines = [json.dumps(r, separators=(",", ":")) for r in self._collector.collect()]
                self._out.write("\n".join(lines) + "\n")
                self._out.flush()
            except Exception:
                log.exception("Failed to publish metrics")

    def stop(self) -> None:
        self._stop_event.set()
