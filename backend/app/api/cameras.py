import base64
import secrets

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.crypto import decrypt, encrypt
from app.db import Camera
from app.deps import CurrentUser, DbSession, Manager, OwnedCamera
from app.schemas import (
    CameraIn,
    CameraOut,
    CameraPatch,
    CameraStatus,
    ProbeIn,
    ProbeOut,
    SourceFields,
    StreamInfoOut,
)
from app.vision.manager import CameraManager
from app.vision.sources import SourceSpec, probe
from app.vision.sources.spec import infer_kind, split_credentials, validate

router = APIRouter(prefix="/api/cameras", tags=["cameras"])

_UNCHANGED = object()


def _resolve_source(fields: SourceFields, current: Camera | None) -> dict:
    """Normalizes the source fields of a create/patch/probe request.

    Returns the camera columns to set. Credentials embedded in a URL are split out, unless
    explicit username/password fields are also given (those win).
    """
    given = fields.model_fields_set
    kind = fields.kind or (current.kind if current and "source" not in given else None)
    source = (
        fields.source.strip()
        if fields.source is not None
        else (current.source if current else None)
    )
    username = fields.username if "username" in given else _UNCHANGED
    password = fields.password if "password" in given else _UNCHANGED

    if "source" in given and source:
        source, url_user, url_password = split_credentials(source)
        # Non-empty explicit fields win; empty ones don't erase what the URL carried.
        if url_user and (username is _UNCHANGED or not username):
            username = url_user
        if url_password and (password is _UNCHANGED or not password):
            password = url_password

    kind = kind or (infer_kind(source) if source else None)
    if kind == "browser":
        source = "browser"
    if not kind or not source:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "source is required")
    if error := validate(kind, source):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error)

    values: dict = {"kind": kind, "source": source}
    if username is not _UNCHANGED:
        values["username"] = username or None
    if password is not _UNCHANGED:
        values["password_enc"] = encrypt(password) if password else None
    if "options" in given:
        values["options"] = fields.options.model_dump(exclude_none=True) if fields.options else None
    return values


def _apply(camera: Camera, values: dict) -> None:
    for column, value in values.items():
        setattr(camera, column, value)
    if camera.kind == "browser":
        camera.publish_token = camera.publish_token or secrets.token_urlsafe(24)
        camera.username = camera.password_enc = None
    else:
        camera.publish_token = None


def camera_status(camera_id: int, manager: CameraManager) -> CameraStatus:
    worker = manager.get(camera_id)
    if worker is None:
        return CameraStatus(
            camera_id=camera_id, state="stopped", error=None, occupancy=0, unique_entries=0, fps=0
        )
    info = worker.stream_info
    publisher = None
    if worker.config.source.kind == "browser":
        publisher = manager.browser_hub.slot(camera_id).publisher_connected
    return CameraStatus(
        camera_id=camera_id,
        state=worker.state,
        error=worker.error,
        error_code=worker.error_code,
        hint=worker.hint,
        occupancy=worker.occupancy,
        unique_entries=worker.unique_entries,
        fps=round(worker.fps, 1),
        stream=StreamInfoOut.model_validate(info) if info else None,
        reconnects=worker.reconnects,
        publisher_connected=publisher,
    )


@router.get("", response_model=list[CameraOut])
def list_cameras(user: CurrentUser, db: DbSession) -> list[Camera]:
    return list(db.scalars(select(Camera).where(Camera.owner_id == user.id).order_by(Camera.id)))


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
def create_camera(body: CameraIn, user: CurrentUser, db: DbSession, manager: Manager) -> Camera:
    camera = Camera(owner_id=user.id, name=body.name, zone=body.zone, threshold=body.threshold)
    _apply(camera, _resolve_source(body, None))
    db.add(camera)
    db.commit()
    manager.upsert(camera)
    return camera


@router.post("/probe", response_model=ProbeOut)
def probe_source(body: ProbeIn, user: CurrentUser, db: DbSession, manager: Manager) -> ProbeOut:
    """Connects to a source once and reports what it sees, without saving anything."""
    current = None
    if body.camera_id is not None:
        current = db.get(Camera, body.camera_id)
        if current is None or current.owner_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    values = _resolve_source(body, current)

    if values["kind"] == "browser":
        if current is None or current.kind != "browser":
            return ProbeOut(
                ok=False,
                error_code="waiting",
                message="Save the camera first, then open its publish link.",
            )
        slot = manager.browser_hub.slot(current.id)
        if not slot.publisher_connected:
            return ProbeOut(ok=False, error_code="waiting", message="No browser is publishing yet.")

    def stored(column: str):
        return getattr(current, column) if current is not None else None

    password_enc = values.get("password_enc", stored("password_enc"))
    spec = SourceSpec(
        kind=values["kind"],
        url=values["source"],
        username=values.get("username", stored("username")),
        password=decrypt(password_enc) if password_enc else None,
        options=values.get("options", stored("options")) or {},
    )
    result = probe(spec, manager.settings, manager.browser_hub, current.id if current else 0)
    return ProbeOut(
        ok=result.ok,
        error_code=result.error_code,
        message=result.message,
        hint=result.hint,
        stream=StreamInfoOut.model_validate(result.info) if result.info else None,
        first_frame_ms=result.first_frame_ms,
        preview="data:image/jpeg;base64," + base64.b64encode(result.preview_jpeg).decode()
        if result.preview_jpeg
        else None,
    )


@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(camera: OwnedCamera) -> Camera:
    return camera


@router.patch("/{camera_id}", response_model=CameraOut)
def update_camera(
    body: CameraPatch, camera: OwnedCamera, db: DbSession, manager: Manager
) -> Camera:
    given = body.model_fields_set
    for field in ("name", "zone", "threshold"):
        if field in given:
            value = getattr(body, field)
            if value is None and field == "name":
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "name cannot be null")
            setattr(camera, field, value)
    if given & set(SourceFields.model_fields):
        _apply(camera, _resolve_source(body, camera))
    db.commit()
    manager.upsert(camera)
    return camera


@router.post("/{camera_id}/publish-token", response_model=CameraOut)
def rotate_publish_token(camera: OwnedCamera, db: DbSession) -> Camera:
    """Issues a new publish link for a browser camera; the old link stops working."""
    if camera.kind != "browser":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only browser cameras have publish links")
    camera.publish_token = secrets.token_urlsafe(24)
    db.commit()
    return camera


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(camera: OwnedCamera, db: DbSession, manager: Manager) -> None:
    manager.remove(camera.id, persist=False)
    db.delete(camera)
    db.commit()


@router.get("/{camera_id}/status", response_model=CameraStatus)
def get_status(camera: OwnedCamera, manager: Manager) -> CameraStatus:
    return camera_status(camera.id, manager)


@router.get(
    "/{camera_id}/snapshot.jpg",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
)
def snapshot(camera: OwnedCamera, manager: Manager) -> Response:
    worker = manager.get(camera.id)
    jpeg = worker.snapshot_jpeg() if worker else None
    if jpeg is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No frame available yet")
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
