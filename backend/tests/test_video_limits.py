"""Public-demo cost controls: the video viewer cap, video session limits, and metrics."""

import io
import json

import numpy as np
import pytest
import supervision as sv
from starlette.websockets import WebSocketDisconnect

from app.config import get_settings
from app.metrics import NAMESPACE, MetricsCollector, MetricsEmitter
from app.vision.detectors import LockedDetector
from tests.conftest import signup
from tests.test_pipeline import wait_for


@pytest.fixture
def camera(client, video_file):
    signup(client)
    cam = client.post("/api/cameras", json={"name": "Clip", "source": video_file}).json()
    worker = client.app.state.manager.get(cam["id"])
    wait_for(lambda: worker.latest_jpeg()[1])
    return cam


def closed_code(ws) -> int:
    with pytest.raises(WebSocketDisconnect) as closed:
        while True:
            ws.receive_bytes()
    return closed.value.code


def test_video_viewers_are_capped_and_slots_are_released(client, camera, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_video_viewers", 1)
    slots = client.app.state.video_slots
    with client.websocket_connect("/api/ws/frames") as first:
        assert first.receive_bytes()[4:6] == b"\xff\xd8"
        assert slots.in_use == 1
        with client.websocket_connect("/api/ws/frames") as second:
            assert closed_code(second) == 4429  # busy: the browser backs off and retries
        r = client.get(f"/api/cameras/{camera['id']}/stream.mjpg")
        assert r.status_code == 503 and r.headers["retry-after"] == "30"
    wait_for(lambda: slots.in_use == 0)
    with client.websocket_connect("/api/ws/frames") as again:
        assert again.receive_bytes()


def test_video_sessions_expire(client, camera, monkeypatch):
    monkeypatch.setattr(get_settings(), "video_session_max_s", 0.3)
    with client.websocket_connect("/api/ws/frames") as ws:
        assert closed_code(ws) == 4408  # expired: the browser asks before resuming
    with client.stream("GET", f"/api/cameras/{camera['id']}/stream.mjpg") as r:
        assert b"".join(r.iter_bytes()).startswith(b"--frame")  # the stream ends by itself


def test_idle_timeout_is_published_to_the_browser(client, monkeypatch):
    assert client.get("/api/config").json()["video_idle_timeout_s"] is None
    monkeypatch.setattr(get_settings(), "video_idle_timeout_s", 600.0)
    assert client.get("/api/config").json()["video_idle_timeout_s"] == 600.0


def test_metrics_are_embedded_metric_format(client, camera):
    manager = client.app.state.manager
    collector = MetricsCollector(manager, client.app.state.video_slots)
    *cameras, fleet = collector.collect(now_ms=1_700_000_000_000)

    (record,) = cameras
    spec = record["_aws"]["CloudWatchMetrics"][0]
    assert record["_aws"]["Timestamp"] == 1_700_000_000_000
    assert spec["Namespace"] == NAMESPACE and spec["Dimensions"] == [["CameraId"]]
    assert {m["Name"] for m in spec["Metrics"]} == {"FPS", "Occupancy", "Alerting", "Reconnects"}
    assert record["CameraId"] == str(camera["id"]) and record["State"] == "running"
    assert all(m["Name"] in record for m in spec["Metrics"])  # every declared metric has a value

    assert fleet["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [[]]
    assert (fleet["Cameras"], fleet["CamerasRunning"], fleet["CamerasStalled"]) == (1, 1, 0)
    assert fleet["Inferences"] > 0 and fleet["InferenceMs"] >= 0 and "LockWaitMs" in fleet


def test_emitter_writes_one_json_line_per_record(client, camera):
    out = io.StringIO()
    collector = MetricsCollector(client.app.state.manager, client.app.state.video_slots)
    emitter = MetricsEmitter(collector, interval_s=0.05, out=out)
    emitter.start()
    wait_for(lambda: out.getvalue().count("\n") >= 2)
    emitter.stop()
    lines = out.getvalue().splitlines()
    assert all(json.loads(line)["_aws"]["CloudWatchMetrics"] for line in lines)


def test_locked_detector_reports_inference_and_queueing_time():
    class Inner:
        name = "inner"

        def detect(self, frame):
            return sv.Detections.empty()

    detector = LockedDetector(Inner())
    for _ in range(3):
        detector.detect(np.zeros((4, 4, 3), np.uint8))
    stats = detector.drain_stats()
    assert stats.inferences == 3 and stats.inference_ms >= 0 and stats.lock_wait_ms >= 0
    assert detector.drain_stats().inferences == 0  # drained
