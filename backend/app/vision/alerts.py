"""When a camera is alerting, and how alerts become incidents. Pure logic, no I/O."""

from dataclasses import dataclass
from typing import Literal

Mode = Literal["occupancy", "danger_zone"]
MODES: tuple[Mode, ...] = ("occupancy", "danger_zone")


def alert_limit(mode: str, threshold: int | None) -> int | None:
    """Most people allowed in the zone before the camera alerts; None = never alerts.

    Occupancy cameras alert only when a threshold is set. Danger zones default to 0, so a
    single person inside is an alert; a threshold allows that many (e.g. a banksman).
    """
    if mode == "danger_zone":
        return threshold or 0
    return threshold


@dataclass(frozen=True)
class IncidentEvent:
    kind: Literal["opened", "closed"]
    at: float  # the tracker's clock, see IncidentTracker.update
    peak: int


class IncidentTracker:
    """Turns a camera's alert flag, sampled over time, into incidents with a start and end.

    Debounced both ways: the alert must hold for `open_after` seconds to open an incident
    (one frame of a false detection is not an intrusion), and be clear for `close_after`
    seconds to close it (a person briefly occluded is still the same incident).
    """

    def __init__(self, open_after: float, close_after: float) -> None:
        self._open_after = open_after
        self._close_after = close_after
        self._alert_since: float | None = None
        self._clear_since: float | None = None
        self._open = False
        self._started_at = 0.0
        self.peak = 0

    @property
    def is_open(self) -> bool:
        return self._open

    def update(self, now: float, alerting: bool, occupancy: int) -> IncidentEvent | None:
        if alerting:
            self._clear_since = None
            if self._alert_since is None:
                if not self._open:
                    self.peak = 0  # a new candidate incident; its peak includes the debounce
                self._alert_since = now
            self.peak = max(self.peak, occupancy)
            if not self._open and now - self._alert_since >= self._open_after:
                self._open, self._started_at = True, self._alert_since
                return IncidentEvent("opened", self._started_at, self.peak)
            return None

        self._alert_since = None
        if not self._open:
            return None
        if self._clear_since is None:
            self._clear_since = now
        if now - self._clear_since >= self._close_after:
            self._open = False
            return IncidentEvent("closed", self._clear_since, self.peak)
        return None
