"""Camera sources against real local servers: MJPEG, snapshot (Basic/Digest), RTSP, HLS."""

import pytest

from app.config import Settings
from app.vision.sources import BrowserHub, SourceSpec, probe
from app.vision.sources.errors import SourceError, classify
from app.vision.sources.spec import infer_kind, split_credentials, validate, with_credentials
from tests import servers

SETTINGS = Settings(open_timeout_s=3, read_timeout_s=3)
needs_ffmpeg = pytest.mark.skipif(servers.FFMPEG is None, reason="ffmpeg not installed")


def run_probe(spec: SourceSpec):
    return probe(spec, SETTINGS, BrowserHub())


# -- spec helpers --------------------------------------------------------------------------


def test_credentials_round_trip_with_special_characters():
    url = with_credentials("rtsp://10.0.0.5:554/Streaming/Channels/101", "admin", "p@ss:w/rd#1")
    assert url == "rtsp://admin:p%40ss%3Aw%2Frd%231@10.0.0.5:554/Streaming/Channels/101"
    assert split_credentials(url) == (
        "rtsp://10.0.0.5:554/Streaming/Channels/101",
        "admin",
        "p@ss:w/rd#1",
    )


def test_split_credentials_without_any():
    assert split_credentials("rtsp://cam/live") == ("rtsp://cam/live", None, None)
    assert split_credentials("/videos/a.mp4") == ("/videos/a.mp4", None, None)


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("rtsp://cam:554/live", "stream"),
        ("rtsps://unifi:7441/abc", "stream"),
        ("srt://cam:9000", "stream"),
        ("http://cam/live.m3u8", "stream"),
        ("http://192.168.1.30:8080/video", "stream"),
        ("http://cam/cgi-bin/snapshot.cgi", "snapshot"),
        ("https://cam/image.jpg", "snapshot"),
        ("0", "webcam"),
        ("/dev/video2", "webcam"),
        ("/videos/lobby.mp4", "file"),
    ],
)
def test_infer_kind(source, kind):
    assert infer_kind(source) == kind


def test_validate():
    assert validate("stream", "ftp://cam/x") is not None
    assert validate("stream", "rtsp:///nohost") is not None
    assert validate("snapshot", "rtsp://cam/x") is not None
    assert validate("webcam", "cam") is not None
    assert validate("file", "/definitely/not/here.mp4") is not None
    assert validate("stream", "rtsp://cam/live") is None


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("method DESCRIBE failed: 401 Unauthorized", "auth"),
        ("Server returned 404 Not Found", "not_found"),
        ("Connection refused", "unreachable"),
        ("nodename nor servname provided, or not known", "unreachable"),
        ("Operation timed out", "timeout"),
    ],
)
def test_classify_by_message(message, code):
    assert classify(RuntimeError(message)).code == code


# -- HTTP sources --------------------------------------------------------------------------


def test_mjpeg_stream():
    with servers.camera_http_server() as base:
        result = run_probe(SourceSpec("stream", f"{base}/video"))
    assert result.ok, result.message
    assert (result.info.width, result.info.height) == (320, 240)
    assert result.info.codec == "mjpeg"
    assert result.preview_jpeg[:2] == b"\xff\xd8"


@pytest.mark.parametrize("auth", ["basic", "digest"])
def test_snapshot_with_auth(auth):
    with servers.camera_http_server(auth=auth) as base:
        spec = SourceSpec("snapshot", f"{base}/snapshot.jpg", "admin", "s3cret!")
        result = run_probe(spec)
        assert result.ok, result.message
        assert result.info.codec == "jpeg"

        bad = run_probe(SourceSpec("snapshot", f"{base}/snapshot.jpg", "admin", "wrong"))
        assert (bad.ok, bad.error_code) == (False, "auth")
        assert bad.hint


def test_mjpeg_auth_failure_is_reported():
    with servers.camera_http_server(auth="basic") as base:
        result = run_probe(SourceSpec("stream", f"{base}/video", "admin", "wrong"))
    assert (result.ok, result.error_code) == (False, "auth")


def test_http_errors_are_classified():
    with servers.camera_http_server() as base:
        assert run_probe(SourceSpec("stream", f"{base}/missing")).error_code == "not_found"
        assert run_probe(SourceSpec("snapshot", f"{base}/missing")).error_code == "not_found"
        assert run_probe(SourceSpec("snapshot", f"{base}/page")).error_code == "invalid"


def test_unreachable():
    result = run_probe(SourceSpec("stream", "rtsp://127.0.0.1:9/live"))
    assert (result.ok, result.error_code) == (False, "unreachable")


def test_hung_camera_times_out_instead_of_blocking():
    import time

    with servers.silent_tcp_server() as port:
        started = time.monotonic()
        result = run_probe(SourceSpec("stream", f"rtsp://127.0.0.1:{port}/live"))
        elapsed = time.monotonic() - started
    assert (result.ok, result.error_code) == (False, "timeout")
    assert elapsed < SETTINGS.open_timeout_s + 3


# -- FFmpeg-served streams -----------------------------------------------------------------


needs_mediamtx = pytest.mark.skipif(
    servers.FFMPEG is None or servers.MEDIAMTX is None, reason="needs ffmpeg and mediamtx"
)


@needs_mediamtx
@pytest.mark.parametrize("transport", ["tcp", "udp", "auto"])
def test_rtsp_stream_with_login(video_file, tmp_path, transport):
    with servers.rtsp_camera(video_file, tmp_path) as url:
        spec = SourceSpec(
            "stream", url, servers.RTSP_USER, servers.RTSP_PASSWORD, {"rtsp_transport": transport}
        )
        result = run_probe(spec)
    assert result.ok, result.message
    assert (result.info.codec, result.info.width) == ("h264", 320)


@needs_mediamtx
def test_rtsp_errors(video_file, tmp_path):
    with servers.rtsp_camera(video_file, tmp_path) as url:
        wrong = run_probe(SourceSpec("stream", url, servers.RTSP_USER, "nope"))
        anonymous = run_probe(SourceSpec("stream", url))
        missing = run_probe(
            SourceSpec(
                "stream", url.replace("/live", "/nope"), servers.RTSP_USER, servers.RTSP_PASSWORD
            )
        )
    assert (wrong.ok, wrong.error_code) == (False, "auth")
    assert anonymous.error_code == "auth"
    assert missing.error_code == "not_found"


@needs_ffmpeg
def test_hls_stream(video_file, tmp_path):
    with servers.ffmpeg_hls_server(video_file, tmp_path) as url:
        result = run_probe(SourceSpec("stream", url))
    assert result.ok, result.message
    assert result.info.codec == "h264"


def test_file_source_loops(video_file):
    from app.vision.sources.pyav import PyAVSource

    source = PyAVSource(SourceSpec("file", video_file), 3, 3)
    try:
        frames = [source.read() for _ in range(100)]  # the clip has 40 frames
    finally:
        source.close()
    assert all(f.shape == (240, 320, 3) for f in frames)


def test_source_error_hint():
    assert SourceError("auth", "x").hint
    assert SourceError("error", "x").hint is None
