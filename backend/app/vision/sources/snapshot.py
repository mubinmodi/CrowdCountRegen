"""Cameras that only serve still images: poll a JPEG/PNG URL at a fixed interval.

Handles Basic and Digest auth (most IP cameras use Digest), choosing whichever the camera
asks for in its 401 challenge.
"""

import time

import cv2
import httpx
import numpy as np

from app.vision.sources.base import StreamInfo
from app.vision.sources.errors import SourceError, classify
from app.vision.sources.pyav import USER_AGENT
from app.vision.sources.spec import SourceSpec

DEFAULT_INTERVAL_MS = 500
MIN_INTERVAL_MS = 100


class SnapshotSource:
    def __init__(self, spec: SourceSpec, open_timeout: float, read_timeout: float) -> None:
        self._url = spec.url
        self._username = spec.username
        self._password = spec.password or ""
        interval_ms = max(
            MIN_INTERVAL_MS, int(spec.options.get("snapshot_interval_ms") or DEFAULT_INTERVAL_MS)
        )
        self._interval = interval_ms / 1000
        self._client = httpx.Client(
            timeout=httpx.Timeout(read_timeout, connect=open_timeout),
            follow_redirects=True,
            verify=not spec.options.get("insecure_tls"),
            headers={"User-Agent": USER_AGENT},
        )
        self._auth: httpx.Auth | None = None
        self._next_at = 0.0
        try:
            first = self._fetch()
        except Exception:
            self._client.close()
            raise
        h, w = first.shape[:2]
        self._pending: np.ndarray | None = first
        self.info = StreamInfo(width=w, height=h, fps=1 / self._interval, codec="jpeg", live=True)

    def _fetch(self) -> np.ndarray:
        try:
            response = self._client.get(self._url, auth=self._auth)
            if response.status_code == 401 and self._auth is None and self._username:
                challenge = response.headers.get("www-authenticate", "").lower()
                self._auth = (
                    httpx.DigestAuth(self._username, self._password)
                    if challenge.startswith("digest")
                    else httpx.BasicAuth(self._username, self._password)
                )
                response = self._client.get(self._url, auth=self._auth)
        except httpx.TimeoutException:
            raise SourceError("timeout", "Snapshot request timed out") from None
        except httpx.ConnectError as e:
            raise classify(e) from None
        except httpx.HTTPError as e:
            raise SourceError("unreachable", f"Snapshot request failed: {e}") from None

        match response.status_code:
            case 200:
                pass
            case 401:
                raise SourceError("auth", "Authentication failed (HTTP 401)")
            case 403:
                raise SourceError("forbidden", "Access forbidden (HTTP 403)")
            case 404:
                raise SourceError("not_found", "Snapshot URL not found (HTTP 404)")
            case code:
                raise SourceError("invalid", f"Camera returned HTTP {code}")

        image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            kind = response.headers.get("content-type", "unknown")
            raise SourceError("invalid", f"Response isn't an image (content-type: {kind})")
        return image

    def read(self) -> np.ndarray:
        if self._pending is not None:
            frame, self._pending = self._pending, None
            self._next_at = time.monotonic() + self._interval
            return frame
        delay = self._next_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._next_at = time.monotonic() + self._interval
        return self._fetch()

    def close(self) -> None:
        self._client.close()
