"""Demo housekeeping: put the scenario cameras back the way they shipped."""

from fastapi import APIRouter

from app.demo import reset_scenarios
from app.deps import CurrentUser, DbSession, Manager
from app.schemas import CameraOut

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.post("/reset", response_model=list[CameraOut])
def reset(user: CurrentUser, db: DbSession, manager: Manager) -> list:
    """Restores every scenario camera's name, mode, zone and limit. Other cameras are kept."""
    cameras = reset_scenarios(db, user.id)
    for camera in cameras:
        manager.upsert(camera)
    return cameras
