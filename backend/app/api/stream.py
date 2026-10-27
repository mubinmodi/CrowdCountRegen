"""Live endpoints: MJPEG video per camera and a WebSocket pushing counts for all cameras.

These are long-lived, so they authenticate with a short-lived DB session up front instead
of holding a request-scoped session open for the whole stream.
"""

import asyncio
import time
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.config import get_settings
from app.db import Camera, SessionLocal
from app.deps import user_from_cookies, websocket_user
from app.vision.manager import CameraManager

router = APIRouter(prefix="/api", tags=["live"])

_STATUS_INTERVAL_S = 0.5
_REFRESH_CAMERAS_S = 5.0


def _authorize_camera(request: Request, camera_id: int) -> None:
    with SessionLocal() as db:
        user = user_from_cookies(request.cookies, db)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
        camera = db.get(Camera, camera_id)
        if camera is None or camera.owner_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")


@router.get("/cameras/{camera_id}/stream.mjpg")
async def mjpeg_stream(camera_id: int, request: Request) -> StreamingResponse:
    await asyncio.to_thread(_authorize_camera, request, camera_id)
    manager: CameraManager = request.app.state.manager
    interval = 1.0 / get_settings().max_fps

    async def frames():
        last_seq = -1
        # Looked up every iteration: editing a camera replaces its worker.
        while (worker := manager.get(camera_id)) is not None:
            if await request.is_disconnected():
                break
            seq, jpeg = worker.latest_jpeg()
            if jpeg is not None and seq != last_seq:
                last_seq = seq
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(jpeg)).encode()
                    + b"\r\n\r\n"
                    + jpeg
                    + b"\r\n"
                )
            await asyncio.sleep(interval)

    return StreamingResponse(
        frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )


def _camera_ids_for(websocket: WebSocket) -> list[int] | None:
    with SessionLocal() as db:
        user = websocket_user(websocket, db)
        if user is None:
            return None
        return list(db.scalars(select(Camera.id).where(Camera.owner_id == user.id)))


@router.websocket("/ws/live")
async def live(websocket: WebSocket) -> None:
    camera_ids = await asyncio.to_thread(_camera_ids_for, websocket)
    if camera_ids is None:
        await websocket.close(code=4401, reason="Not authenticated")
        return
    await websocket.accept()
    manager: CameraManager = websocket.app.state.manager
    refreshed_at = time.monotonic()
    try:
        while True:
            if time.monotonic() - refreshed_at > _REFRESH_CAMERAS_S:
                camera_ids = await asyncio.to_thread(_camera_ids_for, websocket) or []
                refreshed_at = time.monotonic()
            await websocket.send_json(
                {
                    "ts": time.time(),
                    "cameras": [asdict(manager.status(cid)) for cid in camera_ids],
                }
            )
            await asyncio.sleep(_STATUS_INTERVAL_S)
    except WebSocketDisconnect:
        pass
