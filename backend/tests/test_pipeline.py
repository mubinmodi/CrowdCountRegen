"""End-to-end: a real video file flows through worker -> stream/websocket -> DB -> analytics."""

import time

import numpy as np
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


def test_editing_camera_restarts_worker(client, video_file):
    signup(client)
    cam = client.post("/api/cameras", json={"name": "Clip", "source": video_file}).json()
    manager = client.app.state.manager
    first = manager.get(cam["id"])
    client.patch(f"/api/cameras/{cam['id']}", json={"name": "Renamed"})
    assert manager.get(cam["id"]) is first  # name change doesn't affect processing
    client.patch(f"/api/cameras/{cam['id']}", json={"threshold": 3})
    assert manager.get(cam["id"]) is not first
    assert not first.is_alive()


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
