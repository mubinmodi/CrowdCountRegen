"""Browser camera publishing: a phone or laptop streams JPEG frames over a WebSocket.

Authenticated by the camera's publish token (like an RTMP stream key) rather than a login,
so the link can be opened on any device. One publisher per camera; a new one takes over.
"""

import asyncio
import time
from dataclasses import asdict

import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.db import Camera, SessionLocal
from app.vision.manager import CameraManager

router = APIRouter(tags=["publish"])

MAX_FRAME_BYTES = 2 * 1024 * 1024
STATUS_INTERVAL_S = 1.0


def _camera_for_token(token: str) -> tuple[int, str] | None:
    with SessionLocal() as db:
        camera = db.scalar(
            select(Camera).where(Camera.publish_token == token, Camera.kind == "browser")
        )
        return (camera.id, camera.name) if camera else None


def _decode(data: bytes) -> np.ndarray | None:
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


@router.websocket("/api/publish/{token}")
async def publish(websocket: WebSocket, token: str) -> None:
    found = await asyncio.to_thread(_camera_for_token, token)
    if found is None:
        await websocket.close(code=4404, reason="Unknown or revoked publish link")
        return
    camera_id, camera_name = found
    await websocket.accept()
    manager: CameraManager = websocket.app.state.manager
    slot = manager.browser_hub.slot(camera_id)
    generation = slot.attach(websocket.headers.get("user-agent"))
    await websocket.send_json({"type": "hello", "camera": camera_name})

    last_status = 0.0
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if slot.publisher_generation != generation:
                await websocket.close(code=4409, reason="Another device started publishing")
                break
            data = message.get("bytes")
            if data and len(data) <= MAX_FRAME_BYTES:
                frame = await asyncio.to_thread(_decode, data)
                if frame is not None:
                    slot.push(frame)
            if time.monotonic() - last_status >= STATUS_INTERVAL_S:
                last_status = time.monotonic()
                await websocket.send_json({"type": "status", **asdict(manager.status(camera_id))})
    except WebSocketDisconnect:
        pass
    finally:
        slot.detach(generation)
