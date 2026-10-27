"""Caps concurrent video viewers: video is the one cost that grows with every viewer."""

from collections.abc import Callable


class VideoSlots:
    """Counts open video connections against a limit read at acquire time.

    Used only from the asyncio event loop, so it needs no lock.
    """

    def __init__(self, limit: Callable[[], int | None]) -> None:
        self._limit = limit
        self.in_use = 0

    @property
    def full(self) -> bool:
        limit = self._limit()
        return limit is not None and self.in_use >= limit

    def try_acquire(self) -> bool:
        if self.full:
            return False
        self.in_use += 1
        return True

    def release(self) -> None:
        self.in_use = max(0, self.in_use - 1)
