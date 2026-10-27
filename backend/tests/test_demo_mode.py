"""The public demo: no login, and nothing a visitor types makes the server connect anywhere."""

import pytest

from app.config import get_settings
from app.db import Camera, SessionLocal
from app.demo import BY_KEY, ensure_demo_user
from tests.conftest import UNREACHABLE


@pytest.fixture
def demo(client, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "demo_mode", True)
    with SessionLocal() as db:
        user = ensure_demo_user(db)
        video = tmp_path / "lobby.mp4"
        video.write_bytes(b"")  # never decoded: these tests don't start its worker
        camera = Camera(owner_id=user.id, kind="file", source=str(video), scenario="lobby")
        camera.name, camera.mode, camera.threshold = "Renamed lobby", "danger_zone", 99
        db.add(camera)
        db.commit()
        return camera.id


def test_no_login_needed(client, demo):
    assert client.get("/api/config").json()["demo_mode"] is True
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "demo@example.com"
    assert [c["id"] for c in client.get("/api/cameras").json()] == [demo]


def test_only_browser_cameras_can_be_added(client, demo):
    r = client.post("/api/cameras", json={"name": "Probe me", "source": UNREACHABLE})
    assert r.status_code == 403
    assert (
        client.post("/api/cameras/probe", json={"source": "http://169.254.169.254/"}).status_code
        == 403
    )
    assert client.post("/api/onvif/discover").status_code == 403

    phone = client.post("/api/cameras", json={"name": "My phone", "kind": "browser"})
    assert phone.status_code == 201 and phone.json()["publish_token"]
    # ...and it can't be switched to a network source afterwards.
    patched = client.patch(f"/api/cameras/{phone.json()['id']}", json={"source": UNREACHABLE})
    assert patched.status_code == 403


def test_browser_cameras_are_capped(client, demo, monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_max_browser_cameras", 1)
    assert client.post("/api/cameras", json={"name": "A", "kind": "browser"}).status_code == 201
    assert client.post("/api/cameras", json={"name": "B", "kind": "browser"}).status_code == 409


def test_scenarios_can_be_edited_and_reset_but_not_removed_or_resourced(client, demo):
    url = f"/api/cameras/{demo}"
    assert client.patch(
        url, json={"zone": [[0, 0], [1, 0], [1, 1]], "mode": "occupancy"}
    ).is_success
    assert client.patch(url, json={"source": "/etc/passwd", "kind": "file"}).status_code == 403
    assert client.delete(url).status_code == 403

    reset = client.post("/api/demo/reset").json()
    lobby = BY_KEY["lobby"]
    assert [(c["name"], c["mode"], c["threshold"]) for c in reset] == [
        (lobby.name, lobby.mode, lobby.threshold)
    ]
    assert reset[0]["zone"] == [list(p) for p in lobby.zone]


def test_outside_demo_mode_the_rules_do_not_apply(client):
    from tests.conftest import signup

    signup(client)
    assert client.get("/api/config").json()["demo_mode"] is False
    assert (
        client.post("/api/cameras", json={"name": "Cam", "source": UNREACHABLE}).status_code == 201
    )
