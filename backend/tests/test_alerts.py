from app.vision.alerts import IncidentTracker, alert_limit


def test_alert_limit_per_mode():
    assert alert_limit("occupancy", None) is None  # no threshold, no alert
    assert alert_limit("occupancy", 5) == 5
    assert alert_limit("danger_zone", None) == 0  # anyone inside is an intrusion
    assert alert_limit("danger_zone", 2) == 2  # e.g. a banksman and an operator


def feed(tracker, samples):
    """samples: (time, alerting, occupancy) -> the events that came out."""
    return [e for t, a, o in samples if (e := tracker.update(t, a, o)) is not None]


def test_incident_opens_after_alert_holds_and_starts_when_alert_began():
    tracker = IncidentTracker(open_after=1.0, close_after=3.0)
    events = feed(tracker, [(0.0, True, 1), (0.5, True, 2), (1.0, True, 1)])
    # The peak includes the debounce window, where 2 people were inside.
    assert [(e.kind, e.at, e.peak) for e in events] == [("opened", 0.0, 2)]
    assert tracker.is_open


def test_brief_false_detection_does_not_open_an_incident():
    tracker = IncidentTracker(open_after=1.0, close_after=3.0)
    assert feed(tracker, [(0.0, True, 1), (0.5, False, 0), (1.0, True, 1), (1.5, False, 0)]) == []


def test_brief_gap_does_not_close_and_peak_is_tracked():
    tracker = IncidentTracker(open_after=1.0, close_after=3.0)
    samples = [(0.0, True, 1), (1.0, True, 1), (2.0, True, 4), (3.0, False, 0), (4.0, True, 2)]
    assert [e.kind for e in feed(tracker, samples)] == ["opened"]
    assert tracker.is_open and tracker.peak == 4


def test_incident_closes_once_clear_long_enough_at_the_moment_it_cleared():
    tracker = IncidentTracker(open_after=1.0, close_after=3.0)
    samples = [(0.0, True, 1), (1.0, True, 3), (2.0, False, 0), (4.0, False, 0), (5.0, False, 0)]
    events = feed(tracker, samples)
    assert [(e.kind, e.at, e.peak) for e in events] == [("opened", 0.0, 3), ("closed", 2.0, 3)]
    assert not tracker.is_open
    # The next alert is a new incident.
    assert [e.kind for e in feed(tracker, [(6.0, True, 1), (7.0, True, 1)])] == ["opened"]
