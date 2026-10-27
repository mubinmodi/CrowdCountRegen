import numpy as np
import supervision as sv


class FakeDetector:
    """Detects nothing. Lets the app run (and tests pass) without any ML dependencies."""

    name = "fake"

    def detect(self, frame_bgr: np.ndarray) -> sv.Detections:
        return sv.Detections.empty()
