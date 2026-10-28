"""The public demo: a shared demo account and a set of scenario cameras on sample footage.

Scenario videos are not stored in the repo. On first start they are downloaded from their
public sources, trimmed to the part where the camera holds still and scaled down, then
cached in `settings.demo_video_dir`. Each scenario camera is created once its video is ready,
so a fresh deployment fills its live wall over the first minute or two.

    uv run python -m app.demo      # prepare every scenario now (blocking)

Zones and limits were tuned with ZW_DETECTOR_IMGSZ=1280 and ZW_CONFIDENCE=0.3, which the
demo deployment uses: the plaza's distant crowd is mostly invisible at the default 640.
"""

import logging
import os
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import Camera, SessionLocal, User, init_db
from app.security import hash_password

log = logging.getLogger(__name__)

DEMO_EMAIL = "demo@example.com"
DEMO_NAME = "Demo"
_TARGET_WIDTH = 960  # the worker's default frame_width; decoding more is wasted work
_USER_AGENT = "Mozilla/5.0 (Zonewatch demo seeder)"


@dataclass(frozen=True)
class Scenario:
    key: str
    name: str
    description: str
    mode: str  # occupancy | danger_zone
    video_url: str
    credit: str
    zone: list[tuple[float, float]] | None
    threshold: int | None = None
    start_s: float = 0.0  # trim: where the footage settles into a fixed view
    end_s: float | None = None


_ROBOFLOW = "https://media.roboflow.com/supervision/video-examples"
_PEXELS = "https://videos.pexels.com/video-files"

SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="road-crossing",
        name="Road works · live traffic lane",
        description=(
            "Crew crossing an open road next to a work area. The roadway is the danger zone: "
            "anyone on it raises an intrusion until they reach the kerb."
        ),
        mode="danger_zone",
        video_url=f"{_PEXELS}/7259509/7259509-uhd_4096_2160_30fps.mp4",
        credit="Pexels video 7259509",
        # The carriageway: the far kerb runs diagonally, so the waiting crew stays outside.
        zone=[(0.18, 0.64), (0.56, 0.64), (1.0, 0.84), (1.0, 1.0), (0.20, 1.0)],
        start_s=4.6,
    ),
    Scenario(
        key="excavator",
        name="Demolition · excavator swing radius",
        description=(
            "A worker hosing down dust beside a working excavator. The arm's swing radius is "
            "a no-go zone, so the incident stays open while he stands inside it."
        ),
        mode="danger_zone",
        video_url=f"{_PEXELS}/38817827/16500099_1920_1080_30fps.mp4",
        credit="Pexels video 38817827",
        zone=[(0.08, 0.50), (0.30, 0.30), (0.80, 0.30), (0.95, 0.55), (0.95, 0.92), (0.08, 0.92)],
        start_s=4.2,
    ),
    Scenario(
        key="earthworks",
        name="Earthworks · excavation edge",
        description=(
            "Two site engineers walk towards an open excavation just below the frame. The strip "
            "along its edge is an exclusion zone; stepping into it raises an intrusion."
        ),
        mode="danger_zone",
        video_url=f"{_PEXELS}/8964933/8964933-uhd_3840_2160_25fps.mp4",
        credit="Pexels video 8964933",
        zone=[(0.0, 0.77), (1.0, 0.77), (1.0, 1.0), (0.0, 1.0)],
    ),
    Scenario(
        key="market-square",
        name="Public plaza · crowd capacity",
        description=(
            "A busy town square. The zone covers the central walkway and the alert fires when "
            "it holds more people than its safe capacity."
        ),
        mode="occupancy",
        video_url=f"{_ROBOFLOW}/market-square.mp4",
        credit="Roboflow supervision example video",
        zone=[(0.05, 0.35), (0.95, 0.35), (0.95, 0.98), (0.05, 0.98)],
        threshold=32,
        end_s=40.0,
    ),
    Scenario(
        key="subway",
        name="Transit · metro platform",
        description=(
            "A handheld walk along a busy metro platform as a train arrives. Counting the whole "
            "frame; occupancy and unique visitors per minute feed the analytics page."
        ),
        mode="occupancy",
        video_url=f"{_ROBOFLOW}/subway.mp4",
        credit="Roboflow supervision example video",
        zone=None,
        threshold=15,
        end_s=40.0,
    ),
    Scenario(
        key="grocery-store",
        name="Retail · aisle during restocking",
        description=(
            "A narrow aisle limited to one shopper while shelves are restocked. The zone is the "
            "aisle floor only, so people in the cross-aisle beyond aren't counted."
        ),
        mode="occupancy",
        video_url=f"{_ROBOFLOW}/grocery-store.mp4",
        credit="Roboflow supervision example video",
        zone=[(0.40, 0.55), (0.62, 0.55), (0.96, 1.0), (0.30, 1.0)],
        threshold=1,
        end_s=40.0,
    ),
    Scenario(
        key="lobby",
        name="Lobby · entrance zone",
        description=(
            "Foot traffic through an atrium. Only the bottom half is counted, which is how two "
            "cameras with overlapping views avoid counting the same people twice."
        ),
        mode="occupancy",
        video_url=f"{_ROBOFLOW}/people-walking.mp4",
        credit="Roboflow supervision example video",
        zone=[(0.0, 0.5), (1.0, 0.5), (1.0, 1.0), (0.0, 1.0)],
        threshold=13,
    ),
)
BY_KEY = {s.key: s for s in SCENARIOS}


def ensure_demo_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is None:
        password = os.environ.get("ZW_DEMO_PASSWORD", "demo-password")
        user = User(email=DEMO_EMAIL, name=DEMO_NAME, password_hash=hash_password(password))
        db.add(user)
        db.commit()
    return user


def demo_user(db: Session) -> User | None:
    return db.scalar(select(User).where(User.email == DEMO_EMAIL))


def video_path(settings: Settings, scenario: Scenario) -> Path:
    return Path(settings.demo_video_dir).expanduser().resolve() / f"{scenario.key}.mp4"


def prepare_video(settings: Settings, scenario: Scenario) -> Path:
    """Downloads, trims and scales the scenario's clip unless it's already cached."""
    target = video_path(settings, scenario)
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = target.with_suffix(".download")
    log.info("demo: downloading %s", scenario.video_url)
    request = urllib.request.Request(scenario.video_url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, raw.open("wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
    try:
        partial = target.with_suffix(".partial.mp4")
        _transcode(raw, partial, scenario.start_s, scenario.end_s)
        partial.rename(target)  # atomic, so a reader never sees half a file
    finally:
        raw.unlink(missing_ok=True)
    log.info("demo: %s ready", target.name)
    return target


def _transcode(src: Path, dst: Path, start_s: float, end_s: float | None) -> None:
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise RuntimeError(f"Can't decode {src.name}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    size = (_TARGET_WIDTH, round(h * _TARGET_WIDTH / w) // 2 * 2) if w > _TARGET_WIDTH else (w, h)
    writer = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    first, last = round(start_s * fps), round(end_s * fps) if end_s else None
    index = 0
    try:
        while last is None or index < last:
            ok, frame = cap.read()
            if not ok:
                break
            if index >= first:
                writer.write(cv2.resize(frame, size, interpolation=cv2.INTER_AREA))
            index += 1
    finally:
        cap.release()
        writer.release()


def scenario_camera(db: Session, user: User, scenario: Scenario, path: Path) -> Camera:
    """The scenario's camera, created with its default zone and limit if it doesn't exist."""
    camera = db.scalar(
        select(Camera).where(Camera.owner_id == user.id, Camera.scenario == scenario.key)
    )
    if camera is None:
        camera = Camera(owner_id=user.id, kind="file", source=str(path), scenario=scenario.key)
        _apply_defaults(camera, scenario)
        db.add(camera)
    else:
        camera.source = str(path)  # the video dir may have moved between deployments
    db.commit()
    return camera


def _apply_defaults(camera: Camera, scenario: Scenario) -> None:
    camera.name = scenario.name
    camera.description = f"{scenario.description} Footage: {scenario.credit}."
    camera.mode = scenario.mode
    camera.zone = [list(p) for p in scenario.zone] if scenario.zone else None
    camera.threshold = scenario.threshold


def reset_scenarios(db: Session, user_id: int) -> list[Camera]:
    """Restores every scenario camera's name, mode, zone and limit to its defaults."""
    cameras = list(
        db.scalars(select(Camera).where(Camera.owner_id == user_id, Camera.scenario.is_not(None)))
    )
    for camera in cameras:
        if scenario := BY_KEY.get(camera.scenario or ""):
            _apply_defaults(camera, scenario)
    db.commit()
    return cameras


def seed(settings: Settings, on_camera_ready=None) -> None:
    """Prepares every scenario in order; `on_camera_ready(camera)` starts its worker."""
    with SessionLocal() as db:
        user = ensure_demo_user(db)
    for scenario in SCENARIOS:
        try:
            path = prepare_video(settings, scenario)
        except Exception:
            log.exception("demo: couldn't prepare scenario %s; skipping it", scenario.key)
            continue
        with SessionLocal() as db:
            camera = scenario_camera(db, user, scenario, path)
        if on_camera_ready is not None:
            on_camera_ready(camera)


def seed_in_background(settings: Settings, on_camera_ready) -> threading.Thread:
    thread = threading.Thread(
        target=seed, args=(settings, on_camera_ready), daemon=True, name="demo-seed"
    )
    thread.start()
    return thread


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    seed(get_settings())
    print(f"Demo ready: {len(SCENARIOS)} scenarios for {DEMO_EMAIL}")
    print("Start the API with ZW_DEMO_MODE=true to skip the login.")
