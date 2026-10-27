import numpy as np
import supervision as sv
from trackers import ByteTrackTracker

from app.vision.counter import ZoneCounter

FRAME = (200, 100)  # w, h
LEFT_HALF = [(0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)]


def dets(boxes, tracker_ids=None, conf=0.9) -> sv.Detections:
    d = sv.Detections(
        xyxy=np.array(boxes, dtype=float),
        confidence=np.full(len(boxes), conf),
        class_id=np.zeros(len(boxes), dtype=int),
    )
    if tracker_ids is not None:
        d.tracker_id = np.array(tracker_ids)
    return d


def test_whole_frame_when_no_zone():
    counter = ZoneCounter(zone=None)
    result = counter.update(dets([[10, 10, 20, 20], [150, 10, 160, 20]]), FRAME)
    assert result.occupancy == 2


def test_zone_uses_feet_position():
    counter = ZoneCounter(zone=LEFT_HALF)
    # Box straddles the zone edge but its bottom-center (x=95) is inside.
    inside = [50, 10, 140, 90]
    # Bottom-center at x=150: outside.
    outside = [120, 10, 180, 90]
    result = counter.update(dets([inside, outside]), FRAME)
    assert result.in_zone.tolist() == [True, False]
    assert result.occupancy == 1


def test_unique_entries_counted_once_per_track():
    counter = ZoneCounter(zone=LEFT_HALF)
    for _ in range(10):
        counter.update(dets([[10, 10, 30, 60]], tracker_ids=[7]), FRAME)
    assert counter.unique_entries == 1
    counter.update(dets([[10, 10, 30, 60], [40, 10, 60, 60]], tracker_ids=[7, 8]), FRAME)
    assert counter.unique_entries == 2


def test_unconfirmed_tracks_are_not_entries():
    counter = ZoneCounter(zone=None)
    result = counter.update(dets([[10, 10, 30, 60]], tracker_ids=[-1]), FRAME)
    assert result.occupancy == 1
    assert result.new_entries == 0


def test_track_outside_zone_is_not_an_entry_until_it_enters():
    counter = ZoneCounter(zone=LEFT_HALF)
    counter.update(dets([[150, 10, 170, 60]], tracker_ids=[3]), FRAME)
    assert counter.unique_entries == 0
    counter.update(dets([[50, 10, 70, 60]], tracker_ids=[3]), FRAME)
    assert counter.unique_entries == 1


def test_with_real_tracker_person_walking_into_zone():
    """Sanity check of our assumptions about the `trackers` ByteTrack output."""
    tracker = ByteTrackTracker(frame_rate=10, track_activation_threshold=0.4)
    counter = ZoneCounter(zone=LEFT_HALF)
    for step in range(30):
        x = 180 - step * 5  # walks from right to left, ending inside the zone
        tracked = tracker.update(dets([[x - 10, 20, x + 10, 80]]))
        counter.update(tracked, FRAME)
    assert counter.unique_entries == 1
