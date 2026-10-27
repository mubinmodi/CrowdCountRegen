"""Turns the many ways a camera connection can fail into a few actionable error codes."""

import errno
import re
from typing import Literal

import av

ErrorCode = Literal[
    "auth",  # wrong or missing credentials
    "forbidden",  # credentials accepted but access denied
    "not_found",  # host answered but the path/stream doesn't exist
    "unreachable",  # DNS failure, connection refused, no route
    "timeout",  # nothing came back in time
    "unsupported",  # protocol or codec FFmpeg can't handle
    "invalid",  # answered, but not with video/images
    "no_video",  # container has no video track
    "ended",  # stream closed by the camera
    "waiting",  # browser source with no publisher connected (not an error)
    "error",  # anything else
]

HINTS: dict[str, str] = {
    "auth": ("Check the username and password. Some cameras lock out after repeated failures."),
    "forbidden": ("The account works but lacks permission for this stream; check its user rights."),
    "not_found": (
        "The camera answered but the stream path is wrong. Try a brand template or ONVIF discovery."
    ),
    "unreachable": (
        "Check the IP/host and port, and that this server can reach the camera's network."
    ),
    "timeout": (
        "The camera didn't answer in time. Over Wi-Fi or VPN, use TCP transport "
        "or a lower-bitrate sub-stream."
    ),
    "unsupported": "This protocol or codec isn't supported by the server's FFmpeg build.",
    "invalid": (
        "The server answered, but not with video. Check the URL points at a stream, not a web page."
    ),
    "no_video": "The stream has no video track.",
    "ended": "The camera closed the stream; reconnecting.",
    "waiting": "Open the publish link on a phone or laptop to start streaming.",
}


class SourceError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.message = message

    @property
    def hint(self) -> str | None:
        return HINTS.get(self.code)


_TEXT_RULES: list[tuple[re.Pattern[str], ErrorCode, str]] = [
    (re.compile(r"401|unauthori[sz]ed", re.I), "auth", "Authentication failed"),
    (re.compile(r"403|forbidden", re.I), "forbidden", "Access forbidden"),
    (re.compile(r"404|not found|454 session", re.I), "not_found", "Stream not found on the camera"),
    (re.compile(r"connection refused", re.I), "unreachable", "Connection refused"),
    (
        re.compile(r"no route|network is unreachable|host is down", re.I),
        "unreachable",
        "Host unreachable",
    ),
    (
        re.compile(
            r"name or service not known|nodename nor servname|failed to resolve|resolve", re.I
        ),
        "unreachable",
        "Host name could not be resolved",
    ),
    (re.compile(r"timed out|timeout", re.I), "timeout", "Connection timed out"),
    (re.compile(r"protocol not found|unsupported", re.I), "unsupported", "Unsupported protocol"),
]


def classify(exc: BaseException) -> SourceError:
    """Maps PyAV/OS exceptions (and their messages) to a SourceError."""
    if isinstance(exc, SourceError):
        return exc
    detail = str(exc)
    match exc:
        case av.error.HTTPUnauthorizedError():
            return SourceError("auth", "Authentication failed (HTTP 401)")
        case av.error.HTTPForbiddenError():
            return SourceError("forbidden", "Access forbidden (HTTP 403)")
        case av.error.HTTPNotFoundError():
            return SourceError("not_found", "Stream not found (HTTP 404)")
        case av.error.HTTPError():
            return SourceError("invalid", f"HTTP error from camera: {detail}")
        case av.error.ConnectionRefusedError():
            return SourceError(
                "unreachable", "Connection refused: is the port right and the camera on?"
            )
        case av.error.TimeoutError() | TimeoutError():
            return SourceError("timeout", "Connection timed out")
        case av.error.ProtocolNotFoundError() | av.error.DemuxerNotFoundError():
            return SourceError("unsupported", f"Unsupported protocol or format: {detail}")
        case av.error.DecoderNotFoundError():
            return SourceError("unsupported", f"Unsupported video codec: {detail}")
        case av.error.FileNotFoundError() | FileNotFoundError():
            return SourceError("not_found", "File not found on the server")
        case OSError() if getattr(exc, "errno", None) in (
            errno.EHOSTUNREACH,
            errno.ENETUNREACH,
            errno.ECONNREFUSED,
        ):
            return SourceError("unreachable", f"Camera unreachable: {detail}")
    for pattern, code, message in _TEXT_RULES:
        if pattern.search(detail):
            return SourceError(code, f"{message}: {detail}")
    if isinstance(exc, av.error.InvalidDataError):
        return SourceError("invalid", "The source answered but didn't send decodable video")
    return SourceError("error", detail or type(exc).__name__)
