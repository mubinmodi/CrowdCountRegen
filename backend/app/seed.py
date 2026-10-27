"""Creates a demo account with one camera playing a sample video. For local development only.

    uv run python -m app.seed

Downloads Roboflow's public "people walking" clip to data/ if it isn't there yet.
"""

import os
import urllib.request
from pathlib import Path

from sqlalchemy import select

from app.db import Camera, SessionLocal, User, init_db
from app.security import hash_password

DEMO_EMAIL = os.environ.get("CC_DEMO_EMAIL", "demo@example.com")
DEMO_PASSWORD = os.environ.get("CC_DEMO_PASSWORD", "demo-password")
SAMPLE_URL = "https://media.roboflow.com/supervision/video-examples/people-walking.mp4"
SAMPLE_PATH = Path("data/people-walking.mp4")


def main() -> None:
    init_db()
    if not SAMPLE_PATH.exists():
        SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading sample video to {SAMPLE_PATH} ...")
        urllib.request.urlretrieve(SAMPLE_URL, SAMPLE_PATH)

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            user = User(email=DEMO_EMAIL, name="Demo", password_hash=hash_password(DEMO_PASSWORD))
            db.add(user)
            db.flush()
        if not db.scalar(select(Camera).where(Camera.owner_id == user.id)):
            db.add(
                Camera(
                    owner_id=user.id,
                    name="Sample: people walking",
                    kind="file",
                    source=str(SAMPLE_PATH.resolve()),
                    # Bottom half of the frame.
                    zone=[[0.0, 0.5], [1.0, 0.5], [1.0, 1.0], [0.0, 1.0]],
                    threshold=15,
                )
            )
        db.commit()
    print(f"Demo account ready: {DEMO_EMAIL} (password from CC_DEMO_PASSWORD or the default)")
    print("Restart the API server if it is running so it picks up the new camera.")


if __name__ == "__main__":
    main()
