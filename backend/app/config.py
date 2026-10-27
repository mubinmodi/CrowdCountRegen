from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (prefix CC_) or a .env file."""

    model_config = SettingsConfigDict(env_prefix="CC_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./crowdcounting.db"

    # Auth. secret_key MUST be overridden outside local development.
    secret_key: str = "dev-only-insecure-key-change-me-in-production"
    session_cookie: str = "cc_session"
    session_ttl_hours: int = 24 * 7
    cookie_secure: bool = False

    # Detection
    detector: Literal["ultralytics", "rfdetr", "fake"] = "ultralytics"
    detector_model: str = ""  # empty = backend default (models/yolo26n.pt / RF-DETR "nano")
    confidence: float = 0.4
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

    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
