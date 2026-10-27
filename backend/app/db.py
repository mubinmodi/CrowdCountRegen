from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    Connection,
    DateTime,
    Engine,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
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
    # occupancy: alert above `threshold` people. danger_zone: alert above `threshold`, which
    # defaults to 0, so anyone entering the zone triggers it (see app.vision.alerts).
    mode: Mapped[str] = mapped_column(String(20), default="occupancy", server_default="occupancy")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Key of the demo scenario this camera was seeded from (app.demo); None for real cameras.
    scenario: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Incident(Base):
    """A period during which a camera was over its alert limit."""

    __tablename__ = "incidents"
    __table_args__ = (Index("ix_incidents_camera_started", "camera_id", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    peak: Mapped[int] = mapped_column(Integer)  # most people in the zone during the incident
    limit: Mapped[int] = mapped_column(Integer)  # the alert limit at the time
    snapshot: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # annotated JPEG


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


def make_engine(url: str) -> Engine:
    sqlite = url.startswith("sqlite")
    engine = create_engine(url, connect_args={"check_same_thread": False} if sqlite else {})
    if sqlite:

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")  # needed for ON DELETE CASCADE
            cursor.execute("PRAGMA journal_mode=WAL")  # readers don't block the count flusher
            cursor.close()

    return engine


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)

MIGRATIONS = Path(__file__).parent / "migrations"


@contextmanager
def migration_connection(bind: Engine) -> Iterator[Connection]:
    """A connection in a transaction, for running migrations.

    On SQLite, foreign keys are switched off for the duration. Alembic's batch mode changes a
    table by copying it, dropping the original and renaming the copy, and with foreign keys
    on, dropping a parent table deletes every child row (ON DELETE CASCADE): rebuilding
    `cameras` would wipe all counts and incidents. The pragma has no effect inside a
    transaction, so it is set before one begins, and integrity is checked before committing.
    """
    with bind.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        try:
            with connection.begin():
                yield connection
                if sqlite and (
                    broken := connection.exec_driver_sql("PRAGMA foreign_key_check").all()
                ):
                    raise RuntimeError(
                        f"Migration left rows with broken foreign keys: {broken[:5]}"
                    )
        finally:
            if sqlite:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()


def _legacy_revision(inspector) -> str:
    """The revision a database made by create_all() (before migrations existed) matches."""
    columns = {c["name"] for c in inspector.get_columns("cameras")}
    if "mode" in columns and "incidents" in inspector.get_table_names():
        return "0003"
    return "0002" if "kind" in columns else "0001"


def init_db(bind: Engine | None = None, revision: str = "head") -> None:
    """Brings the schema up to `revision` with Alembic migrations."""
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with migration_connection(bind or engine) as connection:
        config.attributes["connection"] = connection
        inspector = inspect(connection)
        tables = inspector.get_table_names()
        if "users" in tables and "alembic_version" not in tables:
            # Record which schema it already has, so only the missing migrations run.
            command.stamp(config, _legacy_revision(inspector))
        command.upgrade(config, revision)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
