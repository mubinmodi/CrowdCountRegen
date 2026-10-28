from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (prefix ZW_) or a .env file."""

    model_config = SettingsConfigDict(env_prefix="ZW_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./zonewatch.db"

    # Auth. secret_key MUST be overridden outside local development.
    secret_key: str = "dev-only-insecure-key-change-me-in-production"
    session_cookie: str = "zw_session"
    session_ttl_hours: int = 24 * 7
    cookie_secure: bool = False

    # Detection
    detector: Literal["ultralytics", "rfdetr", "fake"] = "ultralytics"
    detector_model: str = ""  # empty = backend default (models/yolo26n.pt / RF-DETR "nano")
    confidence: float = 0.4
    # Ultralytics inference size. 640 is the model default; wide shots with small, distant
    # people (a plaza from above) need 1280, which a GPU handles easily.
    detector_imgsz: int = 640
    device: str | None = None  # e.g. "cpu", "cuda:0", "mps"; None = auto

    # Camera workers
    start_workers: bool = True
    max_fps: float = 15.0
    frame_width: int = 960  # frames are resized to this width before inference/streaming
    jpeg_quality: int = 80
    reconnect_delay_s: float = 2.0  # first retry; doubles on each failure
    reconnect_max_delay_s: float = 30.0
    open_timeout_s: float = 8.0  # connecting + reading stream headers
    read_timeout_s: float = 8.0  # max wait for the next frame before reconnecting

    # Analytics: counts are aggregated per minute in memory and flushed on this interval
    flush_interval_s: float = 60.0

    # MJPEG output rate; None = max_fps. Lower it to save bandwidth (e.g. behind a CDN).
    stream_fps: float | None = None

    # Video viewers (the frames socket and MJPEG streams; status updates are not limited).
    # Video is the only part whose cost grows with every viewer, so a public demo caps it.
    max_video_viewers: int | None = None  # None = unlimited; extra viewers get "busy"
    video_session_max_s: float | None = None  # close video after this long; client can resume
    video_idle_timeout_s: float | None = None  # browsers pause video after this long idle

    # CloudWatch Embedded Metric Format: one JSON line per camera, plus one for the whole
    # fleet, written to stdout every interval. Any log shipper to CloudWatch Logs (e.g. the
    # awslogs Docker driver) turns them into metrics, with no SDK calls or credentials here.
    metrics: Literal["off", "emf"] = "off"
    metrics_interval_s: float = 60.0

    # Incidents: an alert must hold this long to open one, and be clear this long to close it.
    # Occupancy hovers around its limit, so it gets a longer clear-down: one busy spell is one
    # incident. A danger zone closes quickly, so separate intrusions stay separate.
    incident_open_after_s: float = 1.0
    incident_close_after_s: float = 3.0
    occupancy_incident_close_after_s: float = 15.0
    incidents_kept_per_camera: int = 200

    # Public demo: no login (everyone is the demo user), scenario cameras are seeded from
    # sample videos, and only browser cameras can be added, so the server never connects to
    # an address a visitor typed in.
    demo_mode: bool = False
    demo_video_dir: str = "data/demo-videos"
    demo_max_browser_cameras: int = 4

    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
