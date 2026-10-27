import base64
import secrets

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.config import get_settings
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
from app.vision.sources import SourceSpec, probe
from app.vision.sources.spec import infer_kind, split_credentials, validate
from app.vision.worker import CameraSnapshot

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


def _demo_forbid(message: str) -> None:
    if get_settings().demo_mode:
        raise HTTPException(status.HTTP_403_FORBIDDEN, message)


def _demo_check_source(values: dict) -> None:
    """In the public demo the server must never connect to an address a visitor typed in
    (that would let anyone probe its private network), so only browser cameras, which push
    frames to us, can be added."""
    if values["kind"] != "browser":
        _demo_forbid("The public demo can only add phone or laptop cameras (Browser type).")


def _apply(camera: Camera, values: dict) -> None:
    for column, value in values.items():
        setattr(camera, column, value)
    if camera.kind == "browser":
        camera.publish_token = camera.publish_token or secrets.token_urlsafe(24)
        camera.username = camera.password_enc = None
    else:
        camera.publish_token = None


@router.get("", response_model=list[CameraOut])
def list_cameras(user: CurrentUser, db: DbSession) -> list[Camera]:
    return list(db.scalars(select(Camera).where(Camera.owner_id == user.id).order_by(Camera.id)))


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
def create_camera(body: CameraIn, user: CurrentUser, db: DbSession, manager: Manager) -> Camera:
    values = _resolve_source(body, None)
    settings = get_settings()
    if settings.demo_mode:
        _demo_check_source(values)
        browsers = db.scalars(
            select(Camera.id).where(Camera.owner_id == user.id, Camera.kind == "browser")
        ).all()
        if len(browsers) >= settings.demo_max_browser_cameras:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "The demo already has as many phone cameras as it allows; remove one first.",
            )
    camera = Camera(
        owner_id=user.id,
        name=body.name,
        zone=body.zone,
        threshold=body.threshold,
        mode=body.mode,
        description=body.description,
    )
    _apply(camera, values)
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
    _demo_check_source(values)

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
    for field in ("name", "zone", "threshold", "mode", "description"):
        if field in given:
            value = getattr(body, field)
            if value is None and field in ("name", "mode"):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, f"{field} cannot be null"
                )
            setattr(camera, field, value)
    if given & set(SourceFields.model_fields):
        if camera.scenario:
            _demo_forbid("Demo scenarios play fixed sample footage; their source can't change.")
        values = _resolve_source(body, camera)
        _demo_check_source(values)
        _apply(camera, values)
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
    if camera.scenario:
        _demo_forbid("Demo scenarios can't be removed; use Reset scenarios to undo changes.")
    manager.remove(camera.id, persist=False)
    db.delete(camera)
    db.commit()


@router.get("/{camera_id}/status", response_model=CameraStatus)
def get_status(camera: OwnedCamera, manager: Manager) -> CameraSnapshot:
    return manager.status(camera.id)


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
