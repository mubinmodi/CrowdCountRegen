from fastapi.testclient import TestClient

from tests.conftest import UNREACHABLE, signup

ZONE = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]


def new_camera(client: TestClient, **overrides) -> dict:
    body = {"name": "Lobby", "source": UNREACHABLE, "threshold": 5} | overrides
    r = client.post("/api/cameras", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_signup_login_logout(client):
    user = signup(client)
    assert client.get("/api/auth/me").json()["email"] == user["email"]

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401

    r = client.post("/api/auth/login", json={"email": "ADA@example.com", "password": "nope-nope"})
    assert r.status_code == 401
    r = client.post(
        "/api/auth/login", json={"email": "ADA@example.com", "password": "correct-horse"}
    )
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_session_cookie_is_httponly(client):
    r = client.post(
        "/api/auth/signup", json={"email": "a@b.co", "name": "A", "password": "longenough"}
    )
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_duplicate_signup_and_weak_password(client):
    signup(client)
    r = client.post(
        "/api/auth/signup", json={"email": "ada@example.com", "name": "x", "password": "longenough"}
    )
    assert r.status_code == 409
    r = client.post("/api/auth/signup", json={"email": "z@z.co", "name": "x", "password": "short"})
    assert r.status_code == 422


def test_requires_auth(client):
    assert client.get("/api/cameras").status_code == 401
    assert client.get("/api/analytics").status_code == 401
    assert client.get("/api/cameras/1/stream.mjpg").status_code == 401


def test_camera_crud(client):
    signup(client)
    cam = new_camera(client, zone=ZONE)
    assert cam["zone"] == ZONE

    assert [c["id"] for c in client.get("/api/cameras").json()] == [cam["id"]]

    r = client.patch(f"/api/cameras/{cam['id']}", json={"name": "Entrance"})
    assert r.json()["name"] == "Entrance"
    assert r.json()["zone"] == ZONE  # omitted fields are untouched

    r = client.patch(f"/api/cameras/{cam['id']}", json={"zone": None})
    assert r.json()["zone"] is None  # explicit null clears the zone

    assert client.get(f"/api/cameras/{cam['id']}/status").json()["camera_id"] == cam["id"]

    assert client.delete(f"/api/cameras/{cam['id']}").status_code == 204
    assert client.get(f"/api/cameras/{cam['id']}").status_code == 404


def test_zone_validation(client):
    signup(client)
    for bad in ([[0.1, 0.1], [0.2, 0.2]], [[0, 0], [2, 0], [0, 1]]):
        r = client.post("/api/cameras", json={"name": "x", "source": "0", "zone": bad})
        assert r.status_code == 422


def test_cannot_touch_other_users_cameras(client):
    signup(client, "owner@example.com")
    cam = new_camera(client)
    client.post("/api/auth/logout")

    signup(client, "intruder@example.com")
    assert client.get("/api/cameras").json() == []
    for method, path in [
        ("get", f"/api/cameras/{cam['id']}"),
        ("patch", f"/api/cameras/{cam['id']}"),
        ("delete", f"/api/cameras/{cam['id']}"),
        ("get", f"/api/cameras/{cam['id']}/snapshot.jpg"),
        ("get", f"/api/cameras/{cam['id']}/stream.mjpg"),
        ("get", f"/api/analytics?camera_id={cam['id']}"),
    ]:
        kwargs = {"json": {"name": "pwned"}} if method == "patch" else {}
        assert getattr(client, method)(path, **kwargs).status_code == 404, path


def test_websocket_requires_auth(client):
    from starlette.websockets import WebSocketDisconnect

    try:
        with client.websocket_connect("/api/ws/live") as ws:
            ws.receive_json()
        raise AssertionError("expected the socket to be closed")
    except WebSocketDisconnect as e:
        assert e.code == 4401
