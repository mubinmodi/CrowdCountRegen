"""Network streams and video files via PyAV (FFmpeg).

Covers RTSP/RTSPS, RTMP, SRT, UDP/RTP, HLS (.m3u8), HTTP MJPEG/FLV/MP4 and local files,
with per-camera transport options and hard open/read timeouts so a dead camera can't hang
its reader thread.
"""

import contextlib
import time
from fractions import Fraction

import av
import numpy as np

from app.vision.sources.base import StreamInfo
from app.vision.sources.errors import SourceError, classify
from app.vision.sources.spec import SourceSpec

USER_AGENT = "Zonewatch/2"


def ffmpeg_options(spec: SourceSpec) -> dict[str, str]:
    opts: dict[str, str] = {}
    if spec.kind == "file":
        return opts
    # Live sources: don't buffer, hand us frames as soon as they decode.
    opts["fflags"] = "nobuffer"
    opts["flags"] = "low_delay"
    if spec.scheme in ("rtsp", "rtsps"):
        transport = spec.options.get("rtsp_transport", "tcp")
        if transport in ("tcp", "udp"):
            opts["rtsp_transport"] = transport
        else:  # "auto": let FFmpeg try UDP, falling back to TCP
            opts["rtsp_flags"] = "prefer_tcp"
    elif spec.scheme in ("http", "https"):
        opts["user_agent"] = USER_AGENT
        if spec.options.get("insecure_tls"):
            opts["tls_verify"] = "0"
    return opts


def _interrupted(exc: Exception, started: float, timeout: float) -> bool:
    """PyAV's timeout aborts FFmpeg I/O, which surfaces as "Immediate exit requested" or,
    through the RTSP layer, "Invalid data". Only elapsed time tells it apart from bad data."""
    return isinstance(exc, (av.error.ExitError, av.error.InvalidDataError)) and (
        time.monotonic() - started >= timeout * 0.8
    )


class PyAVSource:
    def __init__(self, spec: SourceSpec, open_timeout: float, read_timeout: float) -> None:
        target = spec.url if spec.kind == "file" else spec.authenticated_url()
        self._read_timeout = read_timeout
        started = time.monotonic()
        try:
            self._container = av.open(
                target, options=ffmpeg_options(spec), timeout=(open_timeout, read_timeout)
            )
        except Exception as e:
            if _interrupted(e, started, open_timeout):
                raise SourceError("timeout", f"No answer within {open_timeout:g}s") from None
            raise classify(e) from None
        if not self._container.streams.video:
            self._container.close()
            raise SourceError("no_video", "The source has no video track")

        self._stream = self._container.streams.video[0]
        self._stream.thread_type = "AUTO"
        rate = self._stream.average_rate or self._stream.guessed_rate
        ctx = self._stream.codec_context
        self.info = StreamInfo(
            width=ctx.width or None,
            height=ctx.height or None,
            fps=float(rate) if isinstance(rate, Fraction) and rate > 0 else None,
            codec=ctx.name,
            live=spec.kind != "file",
        )
        self._live = self.info.live
        self._packets = self._container.demux(self._stream)
        self._decoded: list[av.VideoFrame] = []

    def read(self) -> np.ndarray:
        # Demux and decode separately: a corrupt packet then costs one packet, whereas an
        # error inside container.decode() would end the whole generator.
        while not self._decoded:
            started = time.monotonic()
            try:
                packet = next(self._packets)
            except StopIteration:
                if self._live:
                    raise SourceError("ended", "The camera closed the stream") from None
                self._container.seek(0)  # files loop so they behave like a camera
                self._packets = self._container.demux(self._stream)
                continue
            except Exception as e:
                if _interrupted(e, started, self._read_timeout):
                    raise SourceError(
                        "timeout", f"No video for {self._read_timeout:g}s; the stream stalled"
                    ) from None
                raise classify(e) from None
            if packet.size == 0:  # end-of-stream flush marker
                continue
            try:
                self._decoded = list(packet.decode())
            except (av.error.InvalidDataError, av.error.EOFError):
                continue  # corrupt or partial packet on a lossy link; skip it
        return self._decoded.pop(0).to_ndarray(format="bgr24")

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._container.close()
