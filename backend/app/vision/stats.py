"""In-memory per-minute aggregation of counts, flushed to the database periodically."""

import threading
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MinuteBucket:
    minute: datetime
    occupancy_sum: int = 0
    frames: int = 0
    peak: int = 0
    entries: int = 0

    @property
    def avg(self) -> float:
        return self.occupancy_sum / self.frames if self.frames else 0.0


@dataclass
class MinuteAggregator:
    """Thread-safe: the worker thread records, the flusher drains completed minutes."""

    _current: MinuteBucket | None = None
    _completed: list[MinuteBucket] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, now: datetime, occupancy: int, new_entries: int) -> None:
        minute = now.replace(second=0, microsecond=0)
        with self._lock:
            if self._current is None or self._current.minute != minute:
                if self._current is not None and self._current.frames:
                    self._completed.append(self._current)
                self._current = MinuteBucket(minute)
            b = self._current
            b.occupancy_sum += occupancy
            b.frames += 1
            b.peak = max(b.peak, occupancy)
            b.entries += new_entries

    def drain(self, include_current: bool = False) -> list[MinuteBucket]:
        with self._lock:
            out, self._completed = self._completed, []
            if include_current and self._current is not None and self._current.frames:
                out.append(self._current)
                self._current = None
            return out
