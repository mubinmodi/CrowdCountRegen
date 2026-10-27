"""Live endpoints: MJPEG video per camera and a WebSocket pushing counts for all cameras.

These are long-lived, so they authenticate with a short-lived DB session up front instead
of holding a request-scoped session open for the whole stream.
"""

import asyncio
import time
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.config import get_settings
from app.db import Camera, SessionLocal
from app.deps import user_from_cookies, websocket_user
from app.viewers import VideoSlots
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
async def mjpeg_stream(
    camera_id: int, request: Request, size: Literal["full", "small"] = "full"
) -> StreamingResponse:
    """`size=small` is a 480 px wide stream for grid tiles, roughly a quarter of the bytes."""
    await asyncio.to_thread(_authorize_camera, request, camera_id)
    manager: CameraManager = request.app.state.manager
    slots: VideoSlots = request.app.state.video_slots
    if slots.full:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Too many people are watching video right now; try again shortly.",
            headers={"Retry-After": "30"},
        )
    settings = get_settings()
    interval = 1.0 / (settings.stream_fps or settings.max_fps)

    async def frames():
        # The slot is taken inside the generator so it is always released: a generator
        # that never started has no `finally` to run.
        if not slots.try_acquire():
            return
        try:
            async for chunk in _mjpeg(manager, camera_id, request, size, interval):
                yield chunk
        finally:
            slots.release()

    return StreamingResponse(
        frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )


async def _mjpeg(manager: CameraManager, camera_id: int, request: Request, size: str,
                 interval: float):  # fmt: skip
    max_s = get_settings().video_session_max_s
    started = time.monotonic()
    last_seq = -1
    # Looked up every iteration: editing a camera replaces its worker.
    while (worker := manager.get(camera_id)) is not None:
        if await request.is_disconnected():
            break
        if max_s is not None and time.monotonic() - started > max_s:
            break
        seq, jpeg = worker.latest_jpeg(small=size == "small")
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


def _camera_ids_for(websocket: WebSocket) -> list[int] | None:
    with SessionLocal() as db:
        user = websocket_user(websocket, db)
        if user is None:
            return None
        return list(db.scalars(select(Camera.id).where(Camera.owner_id == user.id)))


@router.websocket("/ws/frames")
async def frames(websocket: WebSocket, size: Literal["full", "small"] = "small") -> None:
    """Every camera's latest annotated frame over one socket, for the live wall.

    Each binary message is a 4-byte big-endian camera id followed by a JPEG. One socket for
    all tiles sidesteps the browser's six-connections-per-host limit on HTTP/1.1, which a
    wall of long-lived MJPEG responses would exhaust (stalling every other request). Only
    the newest frame is ever sent, so a slow client gets fewer frames, not a backlog.

    Refusals accept first and then close with a code: a socket closed before the handshake
    completes reaches the browser as a generic 1006, and it couldn't tell "busy" apart.
    """
    await websocket.accept()
    camera_ids = await asyncio.to_thread(_camera_ids_for, websocket)
    if camera_ids is None:
        await websocket.close(code=4401, reason="Not authenticated")
        return
    slots: VideoSlots = websocket.app.state.video_slots
    if not slots.try_acquire():
        # 4429: the browser shows "busy" and retries later instead of reconnecting at once.
        await websocket.close(code=4429, reason="Too many video viewers")
        return
    try:
        await _send_frames(websocket, camera_ids, size)
    finally:
        slots.release()


async def _send_frames(websocket: WebSocket, camera_ids: list[int], size: str) -> None:
    manager: CameraManager = websocket.app.state.manager
    settings = get_settings()
    interval = 1.0 / (settings.stream_fps or settings.max_fps)
    sent: dict[int, int] = {}
    started = refreshed_at = time.monotonic()
    try:
        while True:
            if (max_s := settings.video_session_max_s) and time.monotonic() - started > max_s:
                # 4408: the session ran out; the browser offers to resume rather than
                # reconnecting by itself, so an abandoned tab stops costing bandwidth.
                await websocket.close(code=4408, reason="Video session expired")
                return
            if time.monotonic() - refreshed_at > _REFRESH_CAMERAS_S:
                camera_ids = await asyncio.to_thread(_camera_ids_for, websocket) or []
                refreshed_at = time.monotonic()
            for camera_id in camera_ids:
                worker = manager.get(camera_id)
                if worker is None:
                    continue
                seq, jpeg = worker.latest_jpeg(small=size == "small")
                if jpeg is not None and sent.get(camera_id) != seq:
                    sent[camera_id] = seq
                    await websocket.send_bytes(camera_id.to_bytes(4, "big") + jpeg)
            await asyncio.sleep(interval)
    except (WebSocketDisconnect, RuntimeError):  # RuntimeError: sent after the client left
        pass


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
