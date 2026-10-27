"""Small local servers that behave like IP cameras, for source tests."""

import hashlib
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np


def jpeg_frame(i: int = 0, size: tuple[int, int] = (320, 240)) -> bytes:
    w, h = size
    frame = np.full((h, w, 3), 30, np.uint8)
    cv2.rectangle(
        frame, ((i * 7) % (w - 40), 60), ((i * 7) % (w - 40) + 40, 180), (220, 220, 220), -1
    )
    return cv2.imencode(".jpg", frame)[1].tobytes()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class CameraHTTPHandler(BaseHTTPRequestHandler):
    """Routes: /snapshot.jpg, /video (MJPEG), /missing (404), /page (HTML).

    Server attributes: auth = None | "basic" | "digest", username, password.
    """

    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # keep test output clean
        pass

    def _authorized(self) -> bool:
        mode = self.server.auth  # type: ignore[attr-defined]
        if mode is None:
            return True
        header = self.headers.get("Authorization", "")
        user, password = self.server.username, self.server.password  # type: ignore[attr-defined]
        if mode == "basic":
            import base64

            return header == "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        fields = dict(re.findall(r'(\w+)="?([^",]+)"?', header.removeprefix("Digest ")))
        if not header.startswith("Digest ") or fields.get("username") != user:
            return False
        ha1 = hashlib.md5(f"{user}:cam:{password}".encode()).hexdigest()
        ha2 = hashlib.md5(f"GET:{fields.get('uri')}".encode()).hexdigest()
        expected = hashlib.md5(
            f"{ha1}:{fields.get('nonce')}:{fields.get('nc')}:{fields.get('cnonce')}:auth:{ha2}".encode()
        ).hexdigest()
        return fields.get("response") == expected

    def _challenge(self) -> None:
        self.send_response(401)
        if self.server.auth == "digest":  # type: ignore[attr-defined]
            nonce = os.urandom(8).hex()
            self.send_header("WWW-Authenticate", f'Digest realm="cam", qop="auth", nonce="{nonce}"')
        else:
            self.send_header("WWW-Authenticate", 'Basic realm="cam"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if not self._authorized():
            self._challenge()
            return
        if self.path.startswith("/snapshot.jpg"):
            body = jpeg_frame(self.server.counter)  # type: ignore[attr-defined]
            self.server.counter += 1  # type: ignore[attr-defined]
            self._send(200, "image/jpeg", body)
        elif self.path.startswith("/page"):
            self._send(200, "text/html", b"<html>login</html>")
        elif self.path.startswith("/video"):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                for i in range(10_000):
                    body = jpeg_frame(i)
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\n"
                        + f"Content-Length: {len(body)}\r\n\r\n".encode()
                        + body
                        + b"\r\n"
                    )
                    time.sleep(0.04)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def camera_http_server(auth: str | None = None, username: str = "admin", password: str = "s3cret!"):
    server = ThreadingHTTPServer(("127.0.0.1", 0), CameraHTTPHandler)
    server.daemon_threads = True
    server.auth, server.username, server.password, server.counter = auth, username, password, 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@contextmanager
def silent_tcp_server():
    """Accepts connections and never answers: a camera that's hung."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        sock.settimeout(0.2)
        while not stop.is_set():
            try:
                held.append(sock.accept()[0])
            except TimeoutError:
                continue
            except OSError:
                return

    threading.Thread(target=accept, daemon=True).start()
    try:
        yield sock.getsockname()[1]
    finally:
        stop.set()
        for conn in held:
            conn.close()
        sock.close()


FFMPEG = shutil.which("ffmpeg")


MEDIAMTX = shutil.which("mediamtx")
RTSP_USER, RTSP_PASSWORD = "viewer", "s3cret!"


@contextmanager
def rtsp_camera(video: str, workdir: Path):
    """MediaMTX acting as an RTSP camera (viewer login required), fed by FFmpeg.

    Yields the stream URL without credentials; use RTSP_USER / RTSP_PASSWORD to read it.
    """
    port = free_port()
    rtp, srtp = (free_port() & ~1 for _ in range(2))  # RTP must be even, RTCP = RTP + 1
    config = workdir / "mediamtx.yml"
    # Every listener is either off or on a free port, so it coexists with other MediaMTX
    # instances on the machine (e.g. one you run for manual testing).
    config.write_text(
        f"""logLevel: error
rtspAddress: 127.0.0.1:{port}
rtspTransports: [tcp, udp]
rtpAddress: :{rtp}
rtcpAddress: :{rtp + 1}
srtpAddress: :{srtp}
srtcpAddress: :{srtp + 1}
rtmp: no
hls: no
webrtc: no
srt: no
moq: no
api: no
metrics: no
pprof: no
playback: no
authInternalUsers:
  - user: any
    permissions: [{{action: publish}}]
  - user: {RTSP_USER}
    pass: "{RTSP_PASSWORD}"
    permissions: [{{action: read}}]
paths:
  all_others:
"""
    )
    server = subprocess.Popen(
        [MEDIAMTX, str(config)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    url = f"rtsp://127.0.0.1:{port}/live"
    time.sleep(0.5)
    publisher = subprocess.Popen(
        [FFMPEG, "-loglevel", "error", "-re", "-stream_loop", "-1", "-i", video,
         "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-g", "10",
         "-f", "rtsp", "-rtsp_transport", "tcp", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        time.sleep(1.5)  # let the publisher connect and send a keyframe
        if server.poll() is not None or publisher.poll() is not None:
            raise RuntimeError("MediaMTX or the FFmpeg publisher exited early")
        yield url
    finally:
        for proc in (publisher, server):
            proc.kill()
            proc.wait()


@contextmanager
def ffmpeg_hls_server(video: str, workdir: Path):
    """FFmpeg writing a live HLS playlist, served over HTTP."""
    proc = subprocess.Popen(
        [FFMPEG, "-loglevel", "error", "-re", "-stream_loop", "-1", "-i", video,
         "-c:v", "libx264", "-preset", "ultrafast", "-g", "10", "-f", "hls",
         "-hls_time", "0.5", "-hls_list_size", "4", "-hls_flags", "delete_segments",
         str(workdir / "live.m3u8")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def do_GET(self) -> None:
            path = workdir / self.path.lstrip("/").split("?")[0]
            if not path.is_file():
                self.send_response(404)
                self.end_headers()
                return
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        deadline = time.monotonic() + 15
        while not (workdir / "live.m3u8").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        time.sleep(1.5)  # let a couple of segments land
        yield f"http://127.0.0.1:{server.server_address[1]}/live.m3u8"
    finally:
        server.shutdown()
        server.server_close()
        proc.kill()
        proc.wait()
