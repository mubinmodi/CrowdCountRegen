import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analytics, auth, cameras, onvif, publish, stream
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.vision.manager import CameraManager

log = logging.getLogger("crowdcounting")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.secret_key.startswith("dev-only"):
        log.warning("CC_SECRET_KEY is not set; using an insecure development key.")
    init_db()
    manager = CameraManager(settings, SessionLocal)
    app.state.manager = manager
    manager.start()
    yield
    manager.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="CrowdCounting", version="2.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for module in (auth, cameras, stream, analytics, publish, onvif):
        app.include_router(module.router)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "detector": settings.detector}

    return app


app = create_app()
