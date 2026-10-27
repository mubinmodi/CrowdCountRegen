"""Camera sources: open any supported feed as a FrameSource, or probe it once."""

import time
from dataclasses import dataclass

import cv2

from app.config import Settings
from app.vision.sources.base import FrameSource, StreamInfo
from app.vision.sources.browser import BrowserHub, BrowserSource
from app.vision.sources.errors import SourceError, classify
from app.vision.sources.spec import SourceSpec


def open_source(
    spec: SourceSpec, settings: Settings, hub: BrowserHub, camera_id: int
) -> FrameSource:
    """Raises SourceError if the source can't be opened."""
    open_t, read_t = settings.open_timeout_s, settings.read_timeout_s
    try:
        match spec.kind:
            case "stream" | "file":
                from app.vision.sources.pyav import PyAVSource

                return PyAVSource(spec, open_t, read_t)
            case "snapshot":
                from app.vision.sources.snapshot import SnapshotSource

                return SnapshotSource(spec, open_t, read_t)
            case "webcam":
                from app.vision.sources.webcam import WebcamSource

                return WebcamSource(spec)
            case "browser":
                return BrowserSource(hub.slot(camera_id), read_t)
    except SourceError:
        raise
    except Exception as e:
        raise classify(e) from None
    raise SourceError("invalid", f"Unknown source type {spec.kind!r}")


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    error_code: str | None = None
    message: str | None = None
    hint: str | None = None
    info: StreamInfo | None = None
    first_frame_ms: int | None = None
    preview_jpeg: bytes | None = None


def probe(spec: SourceSpec, settings: Settings, hub: BrowserHub, camera_id: int = 0) -> ProbeResult:
    """Connects once, grabs a frame and reports what the source looks like."""
    started = time.monotonic()
    source: FrameSource | None = None
    try:
        source = open_source(spec, settings, hub, camera_id)
        frame = source.read()
    except SourceError as e:
        return ProbeResult(ok=False, error_code=e.code, message=e.message, hint=e.hint)
    finally:
        if source is not None:
            source.close()
    elapsed_ms = round((time.monotonic() - started) * 1000)

    h, w = frame.shape[:2]
    if w > 640:
        frame = cv2.resize(frame, (640, round(h * 640 / w)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    info = source.info
    if info.width is None:  # some demuxers only know the size after decoding
        info = StreamInfo(w, h, info.fps, info.codec, info.live)
    return ProbeResult(
        ok=True,
        info=info,
        first_frame_ms=elapsed_ms,
        preview_jpeg=buf.tobytes() if ok else None,
    )


__all__ = [
    "BrowserHub",
    "FrameSource",
    "ProbeResult",
    "SourceError",
    "SourceSpec",
    "open_source",
    "probe",
]
