import os
import tempfile
from pathlib import Path

# Configure before the app (and its engine) is imported.
_tmp = Path(tempfile.mkdtemp(prefix="zw-tests-"))
os.environ["ZW_DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
os.environ["ZW_DETECTOR"] = "fake"
os.environ["ZW_SECRET_KEY"] = "test-secret-key-with-at-least-32-bytes!!"
os.environ["ZW_RECONNECT_DELAY_S"] = "0.2"
os.environ["ZW_OPEN_TIMEOUT_S"] = "2"
os.environ["ZW_READ_TIMEOUT_S"] = "2"

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine, init_db  # noqa: E402
from app.main import create_app  # noqa: E402

init_db()  # the real migrations, so tests cover them too


@pytest.fixture(autouse=True)
def clean_db():
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    yield


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


# Nothing listens on port 9 locally, so connecting fails fast with "connection refused".
UNREACHABLE = "rtsp://127.0.0.1:9/stream"


def signup(client: TestClient, email: str = "ada@example.com") -> dict:
    r = client.post(
        "/api/auth/signup", json={"email": email, "name": "Ada", "password": "correct-horse"}
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def video_file(tmp_path) -> str:
    """A short synthetic 320x240 video file usable as a camera source."""
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 20, (320, 240))
    for i in range(40):
        frame = np.full((240, 320, 3), 40, dtype=np.uint8)
        cv2.rectangle(frame, (i * 5, 80), (i * 5 + 40, 200), (200, 200, 200), -1)
        writer.write(frame)
    writer.release()
    return str(path)
