"""What a camera source is, independent of how it is read.

Credentials are kept out of the URL everywhere except at the moment a connection is opened,
so they never end up in API responses, logs or the UI.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import quote, unquote, urlsplit, urlunsplit

Kind = Literal["stream", "snapshot", "webcam", "file", "browser"]
KINDS: tuple[Kind, ...] = ("stream", "snapshot", "webcam", "file", "browser")

# Schemes FFmpeg can pull live video from.
STREAM_SCHEMES = {"rtsp", "rtsps", "rtmp", "rtmps", "srt", "udp", "rtp", "http", "https"}
SNAPSHOT_SCHEMES = {"http", "https"}

_SNAPSHOT_HINT = re.compile(r"(snapshot|snap\.cgi|image\.cgi|still|\.jpe?g$|\.png$)", re.I)
_WEBCAM = re.compile(r"^(\d+|/dev/video\d+)$")


@dataclass(frozen=True)
class SourceSpec:
    kind: Kind
    url: str  # never contains credentials; "browser" sources use a placeholder
    username: str | None = None
    password: str | None = None
    options: dict = field(default_factory=dict)

    @property
    def scheme(self) -> str:
        return urlsplit(self.url).scheme.lower()

    def authenticated_url(self) -> str:
        """URL with credentials embedded, for handing to FFmpeg. Never log or return this."""
        return with_credentials(self.url, self.username, self.password)


def infer_kind(source: str) -> Kind:
    source = source.strip()
    if _WEBCAM.match(source):
        return "webcam"
    scheme = urlsplit(source).scheme.lower()
    if scheme in SNAPSHOT_SCHEMES and _SNAPSHOT_HINT.search(urlsplit(source).path):
        return "snapshot"
    if scheme in STREAM_SCHEMES:
        return "stream"
    return "file"


def split_credentials(url: str) -> tuple[str, str | None, str | None]:
    """'rtsp://user:p%40ss@host/x' -> ('rtsp://host/x', 'user', 'p@ss')."""
    parts = urlsplit(url)
    if not parts.scheme or "@" not in parts.netloc:
        return url, None, None
    userinfo, _, hostport = parts.netloc.rpartition("@")
    user, sep, password = userinfo.partition(":")
    clean = urlunsplit((parts.scheme, hostport, parts.path, parts.query, parts.fragment))
    return clean, unquote(user) or None, unquote(password) if sep else None


def with_credentials(url: str, username: str | None, password: str | None) -> str:
    if not username:
        return url
    parts = urlsplit(url)
    userinfo = quote(username, safe="")
    if password:
        userinfo += ":" + quote(password, safe="")
    netloc = f"{userinfo}@{parts.netloc.rpartition('@')[2]}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def validate(kind: Kind, source: str) -> str | None:
    """Returns an error message, or None if `source` is acceptable for `kind`."""
    scheme = urlsplit(source).scheme.lower()
    match kind:
        case "stream":
            if scheme not in STREAM_SCHEMES:
                return f"Stream URLs must start with one of: {', '.join(sorted(STREAM_SCHEMES))}://"
            if not urlsplit(source).hostname and scheme not in ("udp", "rtp"):
                return "Stream URL is missing a host"
        case "snapshot":
            if scheme not in SNAPSHOT_SCHEMES or not urlsplit(source).hostname:
                return "Snapshot URLs must be http:// or https:// with a host"
        case "webcam":
            if not _WEBCAM.match(source):
                return "Webcam source must be a device index like 0, or /dev/videoN"
        case "file":
            if scheme in STREAM_SCHEMES:
                return "That looks like a URL; choose the network stream or snapshot type"
            if not Path(source).expanduser().is_file():
                return f"No such file on the server: {source}"
        case "browser":
            pass
    return None
