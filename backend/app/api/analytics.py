from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.db import Camera, CountSample
from app.deps import CurrentUser, DbSession
from app.schemas import AnalyticsBucket, AnalyticsOut, AnalyticsSummary

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def auto_bucket_minutes(hours: int) -> int:
    for max_hours, minutes in ((2, 1), (12, 5), (48, 15), (24 * 8, 60)):
        if hours <= max_hours:
            return minutes
    return 360


def _as_utc(dt: datetime) -> datetime:
    # SQLite drops tzinfo; everything is stored in UTC.
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def aggregate(
    samples: list[tuple[datetime, float, int, int]],
    range_start: datetime,
    bucket_minutes: int,
) -> tuple[list[AnalyticsBucket], AnalyticsSummary]:
    """Aggregates per-camera minute samples (minute, avg, peak, entries) into time buckets.

    Samples from different cameras in the same minute are summed first, so the combined
    view reports total people across cameras. Combined peaks are therefore an upper bound
    (individual camera peaks may not have happened in the same second).
    """
    per_minute: dict[datetime, list[float]] = defaultdict(lambda: [0.0, 0, 0])
    for minute, avg, peak, entries in samples:
        m = per_minute[_as_utc(minute)]
        m[0] += avg
        m[1] += peak
        m[2] += entries

    width = timedelta(minutes=bucket_minutes)
    buckets: dict[datetime, list[float]] = {}
    for minute, (avg, peak, entries) in sorted(per_minute.items()):
        start = range_start + ((minute - range_start) // width) * width
        b = buckets.setdefault(start, [0.0, 0, 0, 0])  # avg_sum, peak, entries, minutes
        b[0] += avg
        b[1] = max(b[1], peak)
        b[2] += entries
        b[3] += 1

    out = [
        AnalyticsBucket(
            start=start,
            avg_occupancy=round(avg_sum / n, 2),
            peak_occupancy=int(peak),
            entries=int(entries),
        )
        for start, (avg_sum, peak, entries, n) in buckets.items()
    ]

    peak_minute = max(per_minute.items(), key=lambda kv: kv[1][1], default=None)
    summary = AnalyticsSummary(
        peak_occupancy=int(peak_minute[1][1]) if peak_minute else 0,
        peak_at=peak_minute[0] if peak_minute else None,
        avg_occupancy=round(sum(v[0] for v in per_minute.values()) / len(per_minute), 2)
        if per_minute
        else 0.0,
        total_entries=int(sum(v[2] for v in per_minute.values())),
    )
    return out, summary


@router.get("", response_model=AnalyticsOut)
def analytics(
    user: CurrentUser,
    db: DbSession,
    camera_id: int | None = None,
    hours: Annotated[int, Query(ge=1, le=24 * 90)] = 24,
    bucket_minutes: Annotated[int | None, Query(ge=1, le=24 * 60)] = None,
) -> AnalyticsOut:
    camera_ids = select(Camera.id).where(Camera.owner_id == user.id)
    if camera_id is not None:
        if db.scalar(camera_ids.where(Camera.id == camera_id)) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
        camera_ids = camera_ids.where(Camera.id == camera_id)

    bucket_minutes = bucket_minutes or auto_bucket_minutes(hours)
    range_end = datetime.now(UTC)
    range_start = range_end - timedelta(hours=hours)
    # Align to bucket boundaries so buckets are stable between refreshes.
    width = timedelta(minutes=bucket_minutes)
    epoch = datetime(2000, 1, 1, tzinfo=UTC)
    range_start = epoch + ((range_start - epoch) // width) * width

    rows = db.execute(
        select(
            CountSample.minute,
            CountSample.avg_occupancy,
            CountSample.peak_occupancy,
            CountSample.entries,
        ).where(
            CountSample.camera_id.in_(camera_ids),
            CountSample.minute >= range_start,
        )
    ).all()

    buckets, summary = aggregate([tuple(r) for r in rows], range_start, bucket_minutes)
    return AnalyticsOut(
        camera_id=camera_id,
        range_start=range_start,
        range_end=range_end,
        bucket_minutes=bucket_minutes,
        buckets=buckets,
        summary=summary,
    )
