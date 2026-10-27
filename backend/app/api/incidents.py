"""The incident log: periods when a camera was over its alert limit, with a snapshot."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.db import Camera, Incident
from app.deps import CurrentUser, DbSession
from app.schemas import IncidentOut

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("", response_model=list[IncidentOut])
def list_incidents(
    user: CurrentUser,
    db: DbSession,
    camera_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[IncidentOut]:
    """Newest first. The snapshot itself is fetched separately, so the list stays small."""
    query = (
        select(
            Incident.id,
            Incident.camera_id,
            Incident.started_at,
            Incident.ended_at,
            Incident.peak,
            Incident.limit,
            Incident.snapshot.is_not(None).label("has_snapshot"),
        )
        .join(Camera, Camera.id == Incident.camera_id)
        .where(Camera.owner_id == user.id)
        .order_by(Incident.started_at.desc())
        .limit(limit)
    )
    if camera_id is not None:
        query = query.where(Incident.camera_id == camera_id)
    return [IncidentOut.model_validate(row) for row in db.execute(query)]


@router.get(
    "/{incident_id}/snapshot.jpg",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
)
def incident_snapshot(incident_id: int, user: CurrentUser, db: DbSession) -> Response:
    snapshot = db.scalar(
        select(Incident.snapshot)
        .join(Camera, Camera.id == Incident.camera_id)
        .where(Incident.id == incident_id, Camera.owner_id == user.id)
    )
    if snapshot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No snapshot for this incident")
    # Incidents never change their snapshot, so the browser may keep it.
    return Response(snapshot, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})
