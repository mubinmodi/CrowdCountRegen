from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    # stream | snapshot | webcam | file | browser (see app.vision.sources.spec)
    kind: Mapped[str] = mapped_column(String(20), default="stream", server_default="stream")
    # URL, path or device index, never containing credentials.
    source: Mapped[str] = mapped_column(String(1000))
    username: Mapped[str | None] = mapped_column(String(200), nullable=True)
    password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet, see app.crypto
    # Per-source settings, e.g. {"rtsp_transport": "tcp", "snapshot_interval_ms": 500}
    options: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Secret for browser publishing (kind == "browser"); acts like an RTMP stream key.
    publish_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)

    @property
    def has_password(self) -> bool:
        return bool(self.password_enc)

    # Polygon in normalized [0, 1] image coordinates: [[x, y], ...]. Null = whole frame.
    zone: Mapped[list[list[float]] | None] = mapped_column(JSON, nullable=True)
    threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CountSample(Base):
    """Per-camera, per-minute aggregate of zone occupancy and new unique entries."""

    __tablename__ = "count_samples"
    __table_args__ = (UniqueConstraint("camera_id", "minute"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    minute: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    avg_occupancy: Mapped[float] = mapped_column(Float)
    peak_occupancy: Mapped[int] = mapped_column(Integer)
    entries: Mapped[int] = mapped_column(Integer)
    frames: Mapped[int] = mapped_column(Integer, default=0)  # weight for merging partial minutes


_settings = get_settings()
_is_sqlite = _settings.database_url.startswith("sqlite")
engine = create_engine(
    _settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")  # needed for ON DELETE CASCADE
        cursor.execute("PRAGMA journal_mode=WAL")  # readers don't block the count flusher
        cursor.close()


MIGRATIONS = Path(__file__).parent / "migrations"


def init_db() -> None:
    """Brings the schema up to date with Alembic migrations."""
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        inspector = inspect(connection)
        tables = inspector.get_table_names()
        if "users" in tables and "alembic_version" not in tables:
            # Database created with create_all() before migrations existed: record which
            # schema it already has so only the missing migrations run.
            columns = {c["name"] for c in inspector.get_columns("cameras")}
            command.stamp(config, "head" if "kind" in columns else "0001")
        command.upgrade(config, "head")


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
