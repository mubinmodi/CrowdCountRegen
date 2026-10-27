from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class StreamInfo:
    width: int | None
    height: int | None
    fps: float | None  # nominal rate reported by the source, if any
    codec: str | None
    live: bool  # False for files, which are paced and looped by the reader


class FrameSource(Protocol):
    info: StreamInfo

    def read(self) -> np.ndarray:
        """Blocks until the next BGR frame. Raises SourceError when the source fails."""
        ...

    def close(self) -> None: ...
