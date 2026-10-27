"""Database correctness: migrations, the schema matching the models, and writes that must
survive database errors and races. Migration tests use their own throwaway databases."""

import time
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import OperationalError

from app.db import (
    Base,
    CountSample,
    Incident,
    SessionLocal,
    init_db,
    make_engine,
    migration_connection,
)
from app.vision.detectors.fake import FakeDetector
from app.vision.manager import CameraManager
from app.vision.stats import MinuteBucket
from tests.conftest import UNREACHABLE, signup
from tests.test_pipeline import two_people, wait_for


@pytest.fixture
def scratch_engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'scratch.db'}")
    yield engine
    engine.dispose()


def scalar(engine, sql: str):
    with engine.connect() as c:
        return c.execute(sa.text(sql)).scalar()


def seed_0001(engine) -> None:
    init_db(engine, "0001")
    with engine.begin() as c:
        c.execute(sa.text(
            "INSERT INTO users VALUES (1, 'a@b.c', 'A', 'x', '2026-01-01 00:00:00')"
        ))  # fmt: skip
        c.execute(sa.text(
            "INSERT INTO cameras (id, owner_id, name, source, zone, threshold, created_at) "
            "VALUES (1, 1, 'Cam', 'rtsp://user:pw@10.0.0.1/s', NULL, NULL, '2026-01-01 00:00:00')"
        ))  # fmt: skip
        for m in range(3):
            c.execute(sa.text(
                "INSERT INTO count_samples (camera_id, minute, avg_occupancy, peak_occupancy, "
                f"entries, frames) VALUES (1, '2026-01-01 00:0{m}:00', 1.0, 2, 3, 10)"
            ))  # fmt: skip


def test_upgrading_keeps_counts(scratch_engine):
    # 0002 rebuilds `cameras` (SQLite can't add a unique constraint in place). With foreign
    # keys on, dropping the old table used to cascade-delete every count row.
    seed_0001(scratch_engine)
    init_db(scratch_engine)
    assert scalar(scratch_engine, "SELECT count(*) FROM count_samples") == 3
    assert scalar(scratch_engine, "SELECT kind FROM cameras") == "stream"
    assert scalar(scratch_engine, "SELECT username FROM cameras") == "user"  # split out


def test_a_future_table_rebuild_keeps_child_rows(scratch_engine):
    # Any later migration that rebuilds `cameras` must keep its counts and incidents too.
    seed_0001(scratch_engine)
    init_db(scratch_engine)
    with scratch_engine.begin() as c:
        c.execute(sa.text(
            'INSERT INTO incidents (camera_id, started_at, peak, "limit") '
            "VALUES (1, '2026-01-01 00:00:00', 2, 0)"
        ))  # fmt: skip
    with migration_connection(scratch_engine) as connection:
        ops = Operations(MigrationContext.configure(connection))
        with ops.batch_alter_table("cameras", recreate="always") as batch:
            batch.add_column(sa.Column("future", sa.Integer, nullable=True))
    assert scalar(scratch_engine, "SELECT count(*) FROM count_samples") == 3
    assert scalar(scratch_engine, "SELECT count(*) FROM incidents") == 1


def test_foreign_keys_are_enforced_again_after_migrating(scratch_engine):
    seed_0001(scratch_engine)
    init_db(scratch_engine)
    assert scalar(scratch_engine, "PRAGMA foreign_keys") == 1
    with scratch_engine.begin() as c:
        c.execute(sa.text("DELETE FROM cameras WHERE id = 1"))
    assert scalar(scratch_engine, "SELECT count(*) FROM count_samples") == 0  # cascaded


def legacy_tables(engine, *, with_kind: bool) -> None:
    """What create_all() produced before migrations existed."""
    meta = sa.MetaData()
    sa.Table(
        "users",
        meta,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String),
        sa.Column("name", sa.String),
        sa.Column("password_hash", sa.String),
        sa.Column("created_at", sa.DateTime),
    )
    camera_columns = [
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_id", sa.Integer),
        sa.Column("name", sa.String),
        sa.Column("source", sa.String),
        sa.Column("zone", sa.JSON),
        sa.Column("threshold", sa.Integer),
        sa.Column("created_at", sa.DateTime),
    ]
    if with_kind:
        camera_columns += [
            sa.Column("kind", sa.String),
            sa.Column("username", sa.String),
            sa.Column("password_enc", sa.Text),
            sa.Column("options", sa.JSON),
            sa.Column("publish_token", sa.String),
        ]
    sa.Table("cameras", meta, *camera_columns)
    sa.Table(
        "count_samples",
        meta,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("camera_id", sa.Integer),
        sa.Column("minute", sa.DateTime),
        sa.Column("avg_occupancy", sa.Float),
        sa.Column("peak_occupancy", sa.Integer),
        sa.Column("entries", sa.Integer),
        sa.Column("frames", sa.Integer),
    )
    meta.create_all(engine)  # fmt: skip


@pytest.mark.parametrize("with_kind", [False, True], ids=["0001-schema", "0002-schema"])
def test_legacy_databases_get_the_migrations_they_are_missing(scratch_engine, with_kind):
    # A 0002-shaped database used to be stamped as head and skip 0003 entirely.
    legacy_tables(scratch_engine, with_kind=with_kind)
    init_db(scratch_engine)
    inspector = sa.inspect(scratch_engine)
    assert "mode" in {c["name"] for c in inspector.get_columns("cameras")}
    assert "incidents" in inspector.get_table_names()
    assert scalar(scratch_engine, "SELECT version_num FROM alembic_version") == "0003"


def test_migrations_produce_exactly_the_models(scratch_engine):
    # Drift means the next autogenerated migration would "fix" the database to match the
    # models, e.g. silently dropping an index only the migration created.
    init_db(scratch_engine)
    with scratch_engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def locked(*_args, **_kwargs):
    raise OperationalError("UPDATE incidents ...", {}, Exception("database is locked"))


def test_incident_monitor_survives_database_errors(client, video_file, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "incident_open_after_s", 0.2)
    monkeypatch.setattr(FakeDetector, "detect", two_people)
    signup(client)
    for name in ("Pit A", "Pit B"):
        body = {"name": name, "source": video_file, "mode": "danger_zone"}
        client.post("/api/cameras", json=body)
    wait_for(lambda: len(client.get("/api/incidents").json()) == 2)

    manager = client.app.state.manager
    calls = []
    monkeypatch.setattr(manager, "_update_peak", lambda *a: (calls.append(a), locked())[1])
    manager.check_incidents(time.monotonic())  # raised (and killed the thread) before
    assert (
        len({camera_id for camera_id, _ in calls}) == 2
    )  # one camera's error didn't stop the other
    time.sleep(1.2)  # the monitor thread hits the same errors meanwhile
    assert manager._monitor.is_alive()


def test_failed_incident_close_is_retried(client, video_file, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "incident_open_after_s", 0.2)
    monkeypatch.setattr(get_settings(), "incident_close_after_s", 0.3)
    monkeypatch.setattr(FakeDetector, "detect", two_people)
    signup(client)
    cam = client.post(
        "/api/cameras", json={"name": "Pit", "source": video_file, "mode": "danger_zone"}
    ).json()
    wait_for(lambda: client.get("/api/incidents").json())

    manager = client.app.state.manager
    real_write = CameraManager._write_close
    failures = []

    def flaky(self, *args):
        if not failures:
            failures.append(args)
            locked()
        return real_write(self, *args)

    monkeypatch.setattr(CameraManager, "_write_close", flaky)
    client.patch(f"/api/cameras/{cam['id']}", json={"threshold": 5})  # clears the alert
    closed = wait_for(lambda: (i := client.get("/api/incidents").json()[0])["ended_at"] and i)
    assert failures, "the first close attempt should have failed"
    assert closed["ended_at"] and manager._unwritten_closes == {}


def test_count_merge_retries_when_another_writer_inserted_the_same_minute(client, monkeypatch):
    signup(client)
    cam = client.post("/api/cameras", json={"name": "x", "source": UNREACHABLE}).json()
    manager = client.app.state.manager
    minute = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    real_merge = CameraManager._merge
    raced = []

    def merge_then_race(db, camera_id, buckets):
        real_merge(db, camera_id, buckets)  # read: no row yet, so it queues an INSERT
        if not raced:
            raced.append(True)
            with SessionLocal() as other:  # meanwhile another writer stores the same minute
                other.add(CountSample(camera_id=camera_id, minute=minute, avg_occupancy=3.0,
                                      peak_occupancy=5, entries=2, frames=10))  # fmt: skip
                other.commit()

    monkeypatch.setattr(CameraManager, "_merge", staticmethod(merge_then_race))
    bucket = MinuteBucket(minute, occupancy_sum=10, frames=10, peak=3, entries=1)
    manager._persist(cam["id"], [bucket])

    with SessionLocal() as db:
        rows = db.scalars(sa.select(CountSample).where(CountSample.camera_id == cam["id"])).all()
    assert len(rows) == 1  # merged, not lost
    r = rows[0]
    assert (r.avg_occupancy, r.peak_occupancy, r.entries, r.frames) == (2.0, 5, 3, 20)


def test_incident_index_exists_on_a_migrated_database():
    with SessionLocal() as db:
        indexes = {i["name"] for i in sa.inspect(db.get_bind()).get_indexes(Incident.__tablename__)}
    assert "ix_incidents_camera_started" in indexes
