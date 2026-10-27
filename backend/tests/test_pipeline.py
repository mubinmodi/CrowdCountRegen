"""End-to-end: a real video file flows through worker -> stream/websocket -> DB -> analytics."""

import time

import numpy as np
import pytest
import supervision as sv

from app.vision.detectors.fake import FakeDetector
from tests.conftest import UNREACHABLE, signup


def one_person(self, frame):
    h, w = frame.shape[:2]
    return sv.Detections(
        xyxy=np.array([[w * 0.2, h * 0.2, w * 0.4, h * 0.8]]),
        confidence=np.array([0.95]),
        class_id=np.array([0]),
    )


def two_people(self, frame):
    h, w = frame.shape[:2]
    return sv.Detections(
        xyxy=np.array([[w * 0.1, h * 0.2, w * 0.3, h * 0.8], [w * 0.6, h * 0.2, w * 0.8, h * 0.8]]),
        confidence=np.array([0.95, 0.95]),
        class_id=np.array([0, 0]),
    )


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := predicate():
            return result
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def test_video_file_end_to_end(client, video_file, monkeypatch):
    monkeypatch.setattr(FakeDetector, "detect", one_person)
    signup(client)
    cam = client.post(
        "/api/cameras",
        json={"name": "Clip", "source": video_file, "zone": [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]},
    ).json()

    status = wait_for(
        lambda: (
            (s := client.get(f"/api/cameras/{cam['id']}/status").json())["state"] == "running"
            and s["unique_entries"] >= 1
            and s
        )
    )
    assert status["occupancy"] == 1

    snap = client.get(f"/api/cameras/{cam['id']}/snapshot.jpg")
    assert snap.status_code == 200 and snap.content[:2] == b"\xff\xd8"

    with client.stream("GET", f"/api/cameras/{cam['id']}/stream.mjpg") as r:
        assert r.headers["content-type"].startswith("multipart/x-mixed-replace")
        chunk = next(r.iter_bytes())
        assert chunk.startswith(b"--frame")

    with client.websocket_connect("/api/ws/live") as ws:
        msg = ws.receive_json()
        assert msg["cameras"][0]["camera_id"] == cam["id"]
        assert msg["cameras"][0]["occupancy"] == 1

    # Force a flush of the in-progress minute and check analytics see it.
    manager = client.app.state.manager
    manager._persist(cam["id"], manager.get(cam["id"]).stats.drain(include_current=True))
    data = client.get(f"/api/analytics?camera_id={cam['id']}&hours=1").json()
    assert data["summary"]["peak_occupancy"] == 1
    assert data["summary"]["total_entries"] >= 1
    assert len(data["buckets"]) == 1


def test_bad_source_reports_error(client):
    signup(client)
    cam = client.post("/api/cameras", json={"name": "Nope", "source": UNREACHABLE}).json()
    status = wait_for(
        lambda: (
            (s := client.get(f"/api/cameras/{cam['id']}/status").json())["state"] == "error" and s
        )
    )
    assert status["error_code"] == "unreachable"
    assert status["hint"]


def test_only_processing_changes_restart_worker(client, video_file):
    signup(client)
    cam = client.post("/api/cameras", json={"name": "Clip", "source": video_file}).json()
    manager = client.app.state.manager
    first = manager.get(cam["id"])
    client.patch(f"/api/cameras/{cam['id']}", json={"name": "Renamed", "threshold": 3})
    assert manager.get(cam["id"]) is first  # neither affects processing
    client.patch(f"/api/cameras/{cam['id']}", json={"zone": [[0, 0], [1, 0], [1, 1]]})
    assert manager.get(cam["id"]) is not first
    assert not first.is_alive()


def test_alert_threshold_applies_without_resetting_counts(client, video_file, monkeypatch):
    monkeypatch.setattr(FakeDetector, "detect", two_people)
    signup(client)
    cam = client.post(
        "/api/cameras", json={"name": "Clip", "source": video_file, "threshold": 1}
    ).json()
    url = f"/api/cameras/{cam['id']}/status"
    status = wait_for(lambda: (s := client.get(url).json())["unique_entries"] == 2 and s)
    assert (status["occupancy"], status["over_limit"]) == (2, True)

    with client.websocket_connect("/api/ws/live") as ws:
        assert ws.receive_json()["cameras"][0]["over_limit"] is True

    client.patch(f"/api/cameras/{cam['id']}", json={"threshold": 5})
    status = client.get(url).json()
    assert status["over_limit"] is False
    assert status["unique_entries"] == 2  # the same two people, not re-counted

    client.patch(f"/api/cameras/{cam['id']}", json={"threshold": None})
    assert client.get(url).json()["over_limit"] is False


def test_status_of_camera_without_worker_is_stopped(client):
    manager = client.app.state.manager
    status = manager.status(12345)
    assert (status.state, status.occupancy, status.over_limit) == ("stopped", 0, False)


def test_same_minute_from_restarted_worker_is_merged(client):
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.db import CountSample, SessionLocal
    from app.vision.stats import MinuteBucket

    signup(client)
    cam = client.post("/api/cameras", json={"name": "x", "source": UNREACHABLE}).json()
    minute = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    manager = client.app.state.manager
    manager._persist(
        cam["id"], [MinuteBucket(minute, occupancy_sum=30, frames=10, peak=5, entries=2)]
    )
    manager._persist(
        cam["id"], [MinuteBucket(minute, occupancy_sum=10, frames=10, peak=3, entries=1)]
    )

    with SessionLocal() as db:
        rows = db.scalars(select(CountSample).where(CountSample.camera_id == cam["id"])).all()
    assert len(rows) == 1
    r = rows[0]
    assert (r.avg_occupancy, r.peak_occupancy, r.entries, r.frames) == (2.0, 5, 3, 20)


def test_danger_zone_intrusion_opens_and_closes_an_incident(client, video_file, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "incident_open_after_s", 0.2)
    monkeypatch.setattr(get_settings(), "incident_close_after_s", 0.5)
    monkeypatch.setattr(FakeDetector, "detect", two_people)
    signup(client)
    cam = client.post(
        "/api/cameras", json={"name": "Pit", "source": video_file, "mode": "danger_zone"}
    ).json()
    status = wait_for(
        lambda: (s := client.get(f"/api/cameras/{cam['id']}/status").json())["over_limit"] and s
    )
    assert status["alert_limit"] == 0  # danger zones default to nobody allowed inside

    incident = wait_for(lambda: next(iter(client.get("/api/incidents").json()), None))
    assert (incident["camera_id"], incident["ended_at"], incident["limit"]) == (cam["id"], None, 0)
    assert incident["peak"] == 2 and incident["has_snapshot"]
    snap = client.get(f"/api/incidents/{incident['id']}/snapshot.jpg")
    assert snap.status_code == 200 and snap.content[:2] == b"\xff\xd8"

    # Allowing two people inside clears the alert; the incident closes after the debounce.
    client.patch(f"/api/cameras/{cam['id']}", json={"threshold": 2})
    closed = wait_for(lambda: (i := client.get("/api/incidents").json()[0])["ended_at"] and i)
    assert closed["id"] == incident["id"]


def test_incidents_are_owner_scoped(client, video_file, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "incident_open_after_s", 0.2)
    monkeypatch.setattr(FakeDetector, "detect", two_people)
    signup(client)
    client.post("/api/cameras", json={"name": "Pit", "source": video_file, "mode": "danger_zone"})
    incident = wait_for(lambda: next(iter(client.get("/api/incidents").json()), None))

    client.post("/api/auth/logout")
    signup(client, "eve@example.com")
    assert client.get("/api/incidents").json() == []
    assert client.get(f"/api/incidents/{incident['id']}/snapshot.jpg").status_code == 404


def test_small_stream_for_grid_tiles(client, video_file):
    signup(client)
    cam = client.post("/api/cameras", json={"name": "Clip", "source": video_file}).json()
    worker = client.app.state.manager.get(cam["id"])
    wait_for(lambda: worker.latest_jpeg()[1])
    full, small = worker.latest_jpeg()[1], worker.latest_jpeg(small=True)[1]
    assert small[:2] == b"\xff\xd8" and full[:2] == b"\xff\xd8"
    with client.stream("GET", f"/api/cameras/{cam['id']}/stream.mjpg?size=small") as r:
        assert next(r.iter_bytes()).startswith(b"--frame")


def test_frames_socket_sends_tagged_jpegs(client, video_file):
    signup(client)
    cam = client.post("/api/cameras", json={"name": "Clip", "source": video_file}).json()
    worker = client.app.state.manager.get(cam["id"])
    wait_for(lambda: worker.latest_jpeg()[1])
    with client.websocket_connect("/api/ws/frames") as ws:
        message = ws.receive_bytes()
    assert int.from_bytes(message[:4], "big") == cam["id"]
    assert message[4:6] == b"\xff\xd8"


def test_frames_socket_requires_login(client):
    from starlette.websockets import WebSocketDisconnect

    with (
        client.websocket_connect("/api/ws/frames") as ws,
        pytest.raises(WebSocketDisconnect) as closed,
    ):
        ws.receive_bytes()
    assert closed.value.code == 4401
