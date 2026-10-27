"""Camera source handling through the API: credentials, probe, browser publishing, ONVIF."""

import base64
import hashlib
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from starlette.websockets import WebSocketDisconnect

from app.crypto import decrypt
from app.db import Camera, SessionLocal
from app.onvif import OnvifClient, discover
from app.vision.sources import SourceError
from tests import servers
from tests.conftest import UNREACHABLE, signup


def _stored(camera_id: int) -> Camera:
    with SessionLocal() as db:
        return db.get(Camera, camera_id)


# -- credentials ---------------------------------------------------------------------------


def test_credentials_in_url_are_split_out_and_never_returned(client):
    signup(client)
    r = client.post(
        "/api/cameras",
        json={"name": "Gate", "source": "rtsp://admin:hunter2@127.0.0.1:9/Streaming/Channels/101"},
    )
    assert r.status_code == 201, r.text
    cam = r.json()
    assert cam["kind"] == "stream"
    assert cam["source"] == "rtsp://127.0.0.1:9/Streaming/Channels/101"
    assert cam["username"] == "admin"
    assert cam["has_password"] is True
    for response in (r, client.get("/api/cameras"), client.get(f"/api/cameras/{cam['id']}")):
        assert "hunter2" not in response.text

    stored = _stored(cam["id"])
    assert "hunter2" not in stored.password_enc  # encrypted at rest
    assert decrypt(stored.password_enc) == "hunter2"


def test_explicit_credentials_win_over_url(client):
    signup(client)
    cam = client.post(
        "/api/cameras",
        json={
            "name": "Gate",
            "source": "rtsp://old:old@127.0.0.1:9/live",
            "username": "new",
            "password": "fresh",
        },
    ).json()
    assert cam["username"] == "new"
    assert decrypt(_stored(cam["id"]).password_enc) == "fresh"


def test_empty_fields_do_not_erase_url_credentials(client):
    """What the UI sends when credentials were pasted into the URL only."""
    signup(client)
    cam = client.post(
        "/api/cameras",
        json={"name": "Gate", "source": "rtsp://admin:pw@127.0.0.1:9/live", "username": None},
    ).json()
    assert (cam["username"], cam["has_password"]) == ("admin", True)


def test_patch_password_semantics(client):
    signup(client)
    cam = client.post(
        "/api/cameras",
        json={"name": "Gate", "source": UNREACHABLE, "username": "u", "password": "p"},
    ).json()
    # Omitted: unchanged, even when other source fields change.
    r = client.patch(f"/api/cameras/{cam['id']}", json={"options": {"rtsp_transport": "udp"}})
    assert r.json()["has_password"] is True
    assert r.json()["options"] == {"rtsp_transport": "udp"}
    # Explicit null: cleared.
    r = client.patch(f"/api/cameras/{cam['id']}", json={"password": None})
    assert r.json()["has_password"] is False
    assert r.json()["username"] == "u"


def test_source_validation_errors(client):
    signup(client)
    for body in (
        {"name": "x", "source": "ftp://cam/x", "kind": "stream"},
        {"name": "x", "source": "/no/such/file.mp4"},
        {"name": "x", "kind": "webcam", "source": "front-door"},
        {"name": "x"},
        {"name": "x", "source": "rtsp://cam/x", "options": {"rtsp_transport": "carrier-pigeon"}},
    ):
        assert client.post("/api/cameras", json=body).status_code == 422, body


# -- probe ---------------------------------------------------------------------------------


def test_probe_reports_stream_details(client):
    signup(client)
    with servers.camera_http_server() as base:
        r = client.post("/api/cameras/probe", json={"source": f"{base}/video"})
    data = r.json()
    assert data["ok"], data
    assert data["stream"]["codec"] == "mjpeg"
    assert data["stream"]["width"] == 320
    assert data["preview"].startswith("data:image/jpeg;base64,")
    assert data["first_frame_ms"] >= 0


def test_probe_reuses_stored_password(client):
    signup(client)
    with servers.camera_http_server(auth="digest") as base:
        cam = client.post(
            "/api/cameras",
            json={
                "name": "Snap",
                "source": f"{base}/snapshot.jpg",
                "username": "admin",
                "password": "s3cret!",
            },
        ).json()
        assert cam["kind"] == "snapshot"
        # No password in the request: the stored one is used.
        ok = client.post("/api/cameras/probe", json={"camera_id": cam["id"]}).json()
        assert ok["ok"], ok
        bad = client.post(
            "/api/cameras/probe", json={"camera_id": cam["id"], "password": "wrong"}
        ).json()
        assert (bad["ok"], bad["error_code"]) == (False, "auth")


def test_probe_is_owner_scoped(client):
    signup(client, "a@example.com")
    cam = client.post("/api/cameras", json={"name": "x", "source": UNREACHABLE}).json()
    client.post("/api/auth/logout")
    signup(client, "b@example.com")
    assert client.post("/api/cameras/probe", json={"camera_id": cam["id"]}).status_code == 404


# -- browser publishing --------------------------------------------------------------------


def _wait(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := predicate():
            return result
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def test_browser_camera_publish_flow(client):
    signup(client)
    cam = client.post("/api/cameras", json={"name": "Phone", "kind": "browser"}).json()
    assert cam["kind"] == "browser"
    token = cam["publish_token"]
    assert token and len(token) >= 24

    status = lambda: client.get(f"/api/cameras/{cam['id']}/status").json()  # noqa: E731
    _wait(lambda: status()["state"] == "waiting")
    assert status()["publisher_connected"] is False

    with client.websocket_connect(f"/api/publish/{token}") as ws:
        assert ws.receive_json()["type"] == "hello"
        for i in range(30):
            ws.send_bytes(servers.jpeg_frame(i))
        _wait(lambda: status()["state"] == "running")
        assert status()["publisher_connected"] is True
        assert status()["stream"]["width"] == 320

        # A second device takes over; the first is told why on its next frame.
        with client.websocket_connect(f"/api/publish/{token}") as ws2:
            assert ws2.receive_json()["type"] == "hello"
            ws.send_bytes(servers.jpeg_frame(0))
            with pytest.raises(WebSocketDisconnect) as closed:
                while True:
                    ws.receive_json()
            assert closed.value.code == 4409

    # Rotating the token revokes the old link.
    new = client.post(f"/api/cameras/{cam['id']}/publish-token").json()["publish_token"]
    assert new != token
    with (
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect(f"/api/publish/{token}") as ws,
    ):
        ws.receive_json()
    assert closed.value.code == 4404


def test_browser_probe_waits_for_publisher(client):
    signup(client)
    cam = client.post("/api/cameras", json={"name": "Phone", "kind": "browser"}).json()
    r = client.post("/api/cameras/probe", json={"camera_id": cam["id"]}).json()
    assert (r["ok"], r["error_code"]) == (False, "waiting")


def test_switching_away_from_browser_drops_token(client):
    signup(client)
    cam = client.post("/api/cameras", json={"name": "Phone", "kind": "browser"}).json()
    r = client.patch(f"/api/cameras/{cam['id']}", json={"kind": "stream", "source": UNREACHABLE})
    assert r.json()["publish_token"] is None
    assert r.json()["source"] == UNREACHABLE


# -- ONVIF ---------------------------------------------------------------------------------

USER, PASSWORD = "onvif", "pa55"


def _probe_match(xaddr: str) -> bytes:
    return f"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
<s:Body><d:ProbeMatches><d:ProbeMatch>
 <a:EndpointReference><a:Address>urn:uuid:cam-1</a:Address></a:EndpointReference>
 <d:Scopes>onvif://www.onvif.org/name/Lobby_Cam onvif://www.onvif.org/hardware/DS-2CD2143</d:Scopes>
 <d:XAddrs>{xaddr}</d:XAddrs>
</d:ProbeMatch></d:ProbeMatches></s:Body></s:Envelope>""".encode()


class FakeOnvifCamera(BaseHTTPRequestHandler):
    """Answers the handful of ONVIF calls we make, checking the WS-Security digest."""

    def log_message(self, *args) -> None:
        pass

    def _authorized(self, body: str) -> bool:
        import re

        def field(name: str) -> str:
            m = re.search(rf"<{name}[^>]*>([^<]+)</{name}>", body)
            return m.group(1) if m else ""

        nonce, created = base64.b64decode(field("Nonce") or "AA=="), field("Created")
        expected = base64.b64encode(
            hashlib.sha1(nonce + created.encode() + PASSWORD.encode()).digest()
        ).decode()
        return field("Username") == USER and field("Password") == expected

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        port = self.server.server_address[1]
        if "GetSystemDateAndTime" in body:
            reply = "<tds:GetSystemDateAndTimeResponse><tt:UTCDateTime><tt:Date><tt:Year>2026</tt:Year><tt:Month>1</tt:Month><tt:Day>2</tt:Day></tt:Date><tt:Time><tt:Hour>3</tt:Hour><tt:Minute>4</tt:Minute><tt:Second>5</tt:Second></tt:Time></tt:UTCDateTime></tds:GetSystemDateAndTimeResponse>"
        elif not self._authorized(body):
            self._reply(
                "<s:Fault><s:Code><s:Value>s:Sender</s:Value><s:Subcode><s:Value>ter:NotAuthorized</s:Value></s:Subcode></s:Code></s:Fault>",
                400,
            )
            return
        elif "GetDeviceInformation" in body:
            reply = "<tds:GetDeviceInformationResponse><tds:Manufacturer>HIKVISION</tds:Manufacturer><tds:Model>DS-2CD2143</tds:Model></tds:GetDeviceInformationResponse>"
        elif "GetCapabilities" in body:
            reply = f"<tds:GetCapabilitiesResponse><tds:Capabilities><tt:Media><tt:XAddr>http://127.0.0.1:{port}/onvif/media</tt:XAddr></tt:Media></tds:Capabilities></tds:GetCapabilitiesResponse>"
        elif "GetProfiles" in body:
            reply = """<trt:GetProfilesResponse>
<trt:Profiles token="main"><tt:Name>mainStream</tt:Name><tt:VideoEncoderConfiguration><tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>2560</tt:Width><tt:Height>1440</tt:Height></tt:Resolution></tt:VideoEncoderConfiguration></trt:Profiles>
<trt:Profiles token="sub"><tt:Name>subStream</tt:Name><tt:VideoEncoderConfiguration><tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>640</tt:Width><tt:Height>360</tt:Height></tt:Resolution></tt:VideoEncoderConfiguration></trt:Profiles>
</trt:GetProfilesResponse>"""
        elif "GetStreamUri" in body:
            channel = "101" if "<ProfileToken>main<" in body else "102"
            reply = f"<trt:GetStreamUriResponse><trt:MediaUri><tt:Uri>rtsp://{USER}:{PASSWORD}@127.0.0.1:554/Streaming/Channels/{channel}</tt:Uri></trt:MediaUri></trt:GetStreamUriResponse>"
        else:
            reply = ""
        self._reply(reply)

    def _reply(self, inner: str, code: int = 200) -> None:
        envelope = (
            '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
            'xmlns:tds="http://www.onvif.org/ver10/device/wsdl" '
            'xmlns:trt="http://www.onvif.org/ver10/media/wsdl" '
            'xmlns:tt="http://www.onvif.org/ver10/schema" '
            'xmlns:ter="http://www.onvif.org/ver10/error">'
            f"<s:Body>{inner}</s:Body></s:Envelope>"
        ).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/soap+xml")
        self.send_header("Content-Length", str(len(envelope)))
        self.end_headers()
        self.wfile.write(envelope)


@pytest.fixture
def onvif_camera():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOnvifCamera)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/onvif/device_service"
    server.shutdown()
    server.server_close()


def test_onvif_discovery_parses_probe_matches():
    responder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    responder.bind(("127.0.0.1", 0))

    def answer() -> None:
        data, sender = responder.recvfrom(65535)
        assert b"NetworkVideoTransmitter" in data
        responder.sendto(_probe_match("http://192.168.1.64/onvif/device_service"), sender)
        responder.sendto(b"not xml at all", sender)  # other WS-Discovery chatter is ignored

    threading.Thread(target=answer, daemon=True).start()
    devices = discover(timeout=1.0, target=responder.getsockname())
    responder.close()
    assert len(devices) == 1
    d = devices[0]
    assert (d.host, d.name, d.hardware) == ("192.168.1.64", "Lobby Cam", "DS-2CD2143")


def test_onvif_streams(onvif_camera, client):
    signup(client)
    r = client.post(
        "/api/onvif/streams", json={"xaddr": onvif_camera, "username": USER, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["manufacturer"], data["model"]) == ("HIKVISION", "DS-2CD2143")
    assert [(p["token"], p["width"], p["uri"]) for p in data["profiles"]] == [
        ("main", 2560, "rtsp://127.0.0.1:554/Streaming/Channels/101"),
        ("sub", 640, "rtsp://127.0.0.1:554/Streaming/Channels/102"),
    ]
    assert PASSWORD not in r.text  # credentials stripped from returned URIs


def test_onvif_wrong_password(onvif_camera, client):
    signup(client)
    r = client.post(
        "/api/onvif/streams", json={"xaddr": onvif_camera, "username": USER, "password": "x"}
    )
    assert r.status_code == 401


def test_onvif_clock_skew_is_compensated(onvif_camera):
    client = OnvifClient(onvif_camera, USER, PASSWORD)
    try:
        client.sync_clock()  # fake camera claims it's 2026-01-02 03:04:05
        assert abs(client._clock_offset.total_seconds()) > 60
        assert client.streams().profiles  # digest computed with the camera's clock still verifies
    finally:
        client.close()


def test_onvif_rejects_non_http_addresses():
    with pytest.raises(SourceError):
        OnvifClient("file:///etc/passwd", None, None)


# -- migration -----------------------------------------------------------------------------


def test_migration_moves_url_credentials(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from app.db import MIGRATIONS

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0001")
        conn.execute(
            text(
                "INSERT INTO users (id, email, name, password_hash, created_at) "
                "VALUES (1, 'a@b.co', 'A', 'x', '2026-01-01')"
            )
        )
        for i, source in enumerate(
            ["rtsp://admin:p%40ss@10.0.0.2/live", "http://10.0.0.3/snapshot.jpg", "0"], start=1
        ):
            conn.execute(
                text(
                    "INSERT INTO cameras (id, owner_id, name, source, created_at) "
                    f"VALUES ({i}, 1, 'c{i}', :source, '2026-01-01')"
                ),
                {"source": source},
            )
        command.upgrade(config, "head")
        rows = conn.execute(
            text("SELECT kind, source, username, password_enc FROM cameras ORDER BY id")
        ).all()

    assert [(r.kind, r.source, r.username) for r in rows] == [
        ("stream", "rtsp://10.0.0.2/live", "admin"),
        ("snapshot", "http://10.0.0.3/snapshot.jpg", None),
        ("webcam", "0", None),
    ]
    assert decrypt(rows[0].password_enc) == "p@ss"
    assert json.dumps([r.password_enc for r in rows[1:]]) == "[null, null]"
