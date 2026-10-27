from typing import Annotated

from fastapi import Depends, HTTPException, Request, WebSocket, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Camera, User, get_db
from app.demo import demo_user
from app.security import decode_session_token
from app.vision.manager import CameraManager

DbSession = Annotated[Session, Depends(get_db)]


def user_from_cookies(cookies: dict[str, str], db: Session) -> User | None:
    settings = get_settings()
    if settings.demo_mode:
        # No login in the public demo: every visitor is the shared demo user.
        return demo_user(db)
    token = cookies.get(settings.session_cookie)
    user_id = decode_session_token(token) if token else None
    return db.get(User, user_id) if user_id is not None else None


def current_user(request: Request, db: DbSession) -> User:
    user = user_from_cookies(request.cookies, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


def websocket_user(websocket: WebSocket, db: Session) -> User | None:
    return user_from_cookies(websocket.cookies, db)


CurrentUser = Annotated[User, Depends(current_user)]


def get_manager(request: Request) -> CameraManager:
    return request.app.state.manager


Manager = Annotated[CameraManager, Depends(get_manager)]


def owned_camera(camera_id: int, user: CurrentUser, db: DbSession) -> Camera:
    camera = db.get(Camera, camera_id)
    # 404 rather than 403 so camera ids of other users are not discoverable.
    if camera is None or camera.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    return camera


OwnedCamera = Annotated[Camera, Depends(owned_camera)]
