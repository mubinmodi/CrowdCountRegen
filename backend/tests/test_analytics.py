from datetime import UTC, datetime, timedelta

from app.api.analytics import aggregate, auto_bucket_minutes
from app.vision.stats import MinuteAggregator

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def test_minute_aggregator_rolls_over_minutes():
    agg = MinuteAggregator()
    agg.record(T0 + timedelta(seconds=1), occupancy=2, new_entries=2)
    agg.record(T0 + timedelta(seconds=30), occupancy=4, new_entries=1)
    agg.record(T0 + timedelta(minutes=1, seconds=5), occupancy=1, new_entries=0)

    completed = agg.drain()
    assert len(completed) == 1
    b = completed[0]
    assert (b.minute, b.avg, b.peak, b.entries) == (T0, 3.0, 4, 3)

    assert agg.drain() == []
    current = agg.drain(include_current=True)
    assert [(c.minute, c.peak) for c in current] == [(T0 + timedelta(minutes=1), 1)]


def test_aggregate_sums_cameras_then_buckets():
    samples = [
        # minute, avg, peak, entries -- two cameras in the same minute
        (T0, 2.0, 3, 1),
        (T0, 1.0, 2, 4),
        (T0 + timedelta(minutes=5), 6.0, 8, 0),
        (T0 + timedelta(minutes=20), 1.0, 1, 2),
    ]
    buckets, summary = aggregate(samples, range_start=T0, bucket_minutes=15)
    assert [(b.start, b.avg_occupancy, b.peak_occupancy, b.entries) for b in buckets] == [
        (T0, 4.5, 8, 5),  # minutes 0 (3.0, peak 5) and 5 (6.0, peak 8)
        (T0 + timedelta(minutes=15), 1.0, 1, 2),
    ]
    assert summary.peak_occupancy == 8
    assert summary.peak_at == T0 + timedelta(minutes=5)
    assert summary.total_entries == 7


def test_aggregate_handles_naive_sqlite_datetimes_and_empty():
    buckets, summary = aggregate([(T0.replace(tzinfo=None), 1.0, 1, 0)], T0, 60)
    assert buckets[0].start == T0
    assert aggregate([], T0, 60)[1].peak_occupancy == 0


def test_auto_bucket_minutes():
    assert auto_bucket_minutes(1) == 1
    assert auto_bucket_minutes(24) == 15
    assert auto_bucket_minutes(24 * 7) == 60
    assert auto_bucket_minutes(24 * 30) == 360
