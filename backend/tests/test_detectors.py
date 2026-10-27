"""Smoke tests against the real models. Opt-in, since they download weights:

CC_RUN_MODEL_TESTS=1 uv run --extra yolo --extra rfdetr pytest tests/test_detectors.py
"""

import os
import urllib.request

import cv2
import numpy as np
import pytest

from app.config import Settings
from app.vision.detectors import build_detector

pytestmark = pytest.mark.skipif(
    os.environ.get("CC_RUN_MODEL_TESTS") != "1", reason="set CC_RUN_MODEL_TESTS=1"
)

BUS_IMAGE = "https://ultralytics.com/images/bus.jpg"  # 4 people + a bus


@pytest.fixture(scope="module")
def bus_image() -> np.ndarray:
    data = urllib.request.urlopen(BUS_IMAGE, timeout=30).read()
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


@pytest.mark.parametrize("backend", ["ultralytics", "rfdetr"])
def test_detects_only_people(backend, bus_image):
    pytest.importorskip({"ultralytics": "ultralytics", "rfdetr": "rfdetr"}[backend])
    detector = build_detector(Settings(detector=backend, confidence=0.4))
    detections = detector.detect(bus_image)
    assert len(detections) == 4
