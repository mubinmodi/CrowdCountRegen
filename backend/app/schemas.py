from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Point = tuple[float, float]


class SignupIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str


def _validate_zone(zone: list[Point] | None) -> list[Point] | None:
    if zone is None:
        return None
    if len(zone) < 3:
        raise ValueError("zone needs at least 3 points")
    for x, y in zone:
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ValueError("zone points must be normalized to [0, 1]")
    return zone


SourceKind = Literal["stream", "snapshot", "webcam", "file", "browser"]


class SourceOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rtsp_transport: Literal["tcp", "udp", "auto"] | None = None
    snapshot_interval_ms: int | None = Field(default=None, ge=100, le=60_000)
    insecure_tls: bool | None = None  # accept self-signed HTTPS certificates
    width: int | None = Field(default=None, ge=160, le=4096)  # webcam capture width


class SourceFields(BaseModel):
    """How to reach a camera. `kind` is inferred from `source` when omitted.

    Credentials may be given separately or embedded in the URL (user:pass@host); either way
    they are stored encrypted and never returned.
    """

    kind: SourceKind | None = None
    source: str | None = Field(default=None, max_length=1000)
    username: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, max_length=200)
    options: SourceOptions | None = None


class CameraIn(SourceFields):
    name: str = Field(min_length=1, max_length=200)
    zone: list[Point] | None = None
    threshold: int | None = Field(default=None, ge=1)

    _check_zone = field_validator("zone")(_validate_zone)


class CameraPatch(SourceFields):
    """Omitted fields are unchanged. `password: null` clears it; `zone: null` = whole frame."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    zone: list[Point] | None = None
    threshold: int | None = Field(default=None, ge=1)

    _check_zone = field_validator("zone")(_validate_zone)


class CameraOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    kind: SourceKind
    source: str
    username: str | None
    has_password: bool
    options: dict | None
    zone: list[Point] | None
    threshold: int | None
    publish_token: str | None
    created_at: datetime


class StreamInfoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    width: int | None
    height: int | None
    fps: float | None
    codec: str | None
    live: bool


class CameraStatus(BaseModel):
    camera_id: int
    # "starting" | "connecting" | "running" | "waiting" | "error" | "stopped"
    state: str
    error: str | None
    error_code: str | None = None
    hint: str | None = None
    occupancy: int
    unique_entries: int
    fps: float
    stream: StreamInfoOut | None = None
    reconnects: int = 0
    publisher_connected: bool | None = None  # browser cameras only
    over_limit: bool = False  # occupancy is above the camera's alert threshold


class ProbeIn(SourceFields):
    camera_id: int | None = None  # reuse this camera's stored credentials when not given


class ProbeOut(BaseModel):
    ok: bool
    error_code: str | None = None
    message: str | None = None
    hint: str | None = None
    stream: StreamInfoOut | None = None
    first_frame_ms: int | None = None
    preview: str | None = None  # data:image/jpeg;base64,...


class AnalyticsBucket(BaseModel):
    start: datetime
    avg_occupancy: float
    peak_occupancy: int
    entries: int


class AnalyticsSummary(BaseModel):
    peak_occupancy: int
    peak_at: datetime | None
    avg_occupancy: float
    total_entries: int


class AnalyticsOut(BaseModel):
    camera_id: int | None  # None = all of the user's cameras combined
    range_start: datetime
    range_end: datetime
    bucket_minutes: int
    buckets: list[AnalyticsBucket]
    summary: AnalyticsSummary
