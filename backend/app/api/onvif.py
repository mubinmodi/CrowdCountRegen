import errno
import sys

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.deps import CurrentUser
from app.onvif import OnvifClient, discover
from app.vision.sources import SourceError
from app.vision.sources.spec import split_credentials

router = APIRouter(prefix="/api/onvif", tags=["onvif"])


class DeviceOut(BaseModel):
    xaddr: str
    host: str
    name: str | None
    hardware: str | None


class StreamsIn(BaseModel):
    xaddr: str = Field(max_length=500)
    username: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, max_length=200)


class ProfileOut(BaseModel):
    token: str
    name: str | None
    encoding: str | None
    width: int | None
    height: int | None
    uri: str | None  # without credentials


class StreamsOut(BaseModel):
    manufacturer: str | None
    model: str | None
    profiles: list[ProfileOut]


@router.post("/discover", response_model=list[DeviceOut])
def discover_devices(user: CurrentUser) -> list:
    """Scans the server's local network for ONVIF cameras (takes ~3 seconds).

    Multicast doesn't cross routers or Docker bridge networks; run the backend with host
    networking to discover cameras from a container.
    """
    try:
        return discover()
    except OSError as e:
        if e.errno == errno.EHOSTUNREACH and sys.platform == "darwin":
            detail = (
                "macOS blocked the network scan. Allow Local Network access for the app running "
                "the backend (System Settings → Privacy & Security → Local Network), or enter "
                "the camera's IP below."
            )
        else:
            detail = f"Network scan failed ({e.strerror or e}). Enter the camera's IP below."
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail) from None


@router.post("/streams", response_model=StreamsOut)
def device_streams(body: StreamsIn, user: CurrentUser) -> StreamsOut:
    """Logs into an ONVIF camera and lists its media profiles with RTSP URLs."""
    client = OnvifClient(body.xaddr, body.username, body.password)
    try:
        result = client.streams()
    except SourceError as e:
        code = status.HTTP_401_UNAUTHORIZED if e.code == "auth" else status.HTTP_502_BAD_GATEWAY
        raise HTTPException(code, e.message) from None
    finally:
        client.close()
    return StreamsOut(
        manufacturer=result.manufacturer,
        model=result.model,
        profiles=[
            ProfileOut(
                token=p.token,
                name=p.name,
                encoding=p.encoding,
                width=p.width,
                height=p.height,
                uri=split_credentials(p.uri)[0] if p.uri else None,
            )
            for p in result.profiles
        ],
    )
