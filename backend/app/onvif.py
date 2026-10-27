"""Minimal ONVIF client: find cameras on the LAN and ask them for their RTSP stream URLs.

Implements just what camera setup needs, without a SOAP framework:
  * WS-Discovery multicast probe for NetworkVideoTransmitter devices
  * Device: GetSystemDateAndTime, GetDeviceInformation, GetCapabilities(Media)
  * Media (ver10): GetProfiles, GetStreamUri
Authentication is WS-Security UsernameToken (password digest), timed against the camera's
clock to survive clock skew, with an HTTP Digest retry for cameras that also require it.
"""

import base64
import hashlib
import os
import socket
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlsplit

import httpx

from app.vision.sources.errors import SourceError

MULTICAST = ("239.255.255.250", 3702)
_SOAP = "application/soap+xml; charset=utf-8"

_PROBE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
  xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
  xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:{message_id}</w:MessageID>
    <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>
</e:Envelope>"""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first(root: ET.Element, name: str) -> ET.Element | None:
    return next((el for el in root.iter() if _local(el.tag) == name), None)


def _text(root: ET.Element | None, name: str) -> str | None:
    if root is None:
        return None
    el = _first(root, name)
    return el.text.strip() if el is not None and el.text else None


@dataclass
class Device:
    xaddr: str  # device service URL, e.g. http://192.168.1.20/onvif/device_service
    host: str
    name: str | None = None
    hardware: str | None = None
    endpoint: str | None = None  # stable device UUID, for de-duplication


def _scope(scopes: list[str], key: str) -> str | None:
    prefix = f"onvif://www.onvif.org/{key}/"
    for scope in scopes:
        if scope.startswith(prefix):
            return unquote(scope[len(prefix) :]).replace("_", " ")
    return None


def parse_probe_match(payload: bytes) -> list[Device]:
    root = ET.fromstring(payload)
    devices = []
    for match in (el for el in root.iter() if _local(el.tag) == "ProbeMatch"):
        xaddrs = (_text(match, "XAddrs") or "").split()
        if not xaddrs:
            continue
        # Prefer an IPv4 http address when a device lists several.
        xaddr = next((x for x in xaddrs if "[" not in x), xaddrs[0])
        scopes = (_text(match, "Scopes") or "").split()
        devices.append(
            Device(
                xaddr=xaddr,
                host=urlsplit(xaddr).hostname or "",
                name=_scope(scopes, "name"),
                hardware=_scope(scopes, "hardware"),
                endpoint=_text(match, "Address"),
            )
        )
    return devices


def discover(timeout: float = 3.0, target: tuple[str, int] = MULTICAST) -> list[Device]:
    """Multicasts a WS-Discovery probe and collects replies for `timeout` seconds."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.25)
        sock.bind(("", 0))
        sock.sendto(_PROBE.format(message_id=uuid.uuid4()).encode(), target)
        found: dict[str, Device] = {}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                payload, _ = sock.recvfrom(65535)
            except TimeoutError:
                continue
            try:
                for device in parse_probe_match(payload):
                    found.setdefault(device.endpoint or device.xaddr, device)
            except ET.ParseError:
                continue  # some other WS-Discovery chatter
        return sorted(found.values(), key=lambda d: d.host)
    finally:
        sock.close()


@dataclass
class Profile:
    token: str
    name: str | None
    encoding: str | None
    width: int | None
    height: int | None
    uri: str | None


@dataclass
class DeviceStreams:
    manufacturer: str | None
    model: str | None
    profiles: list[Profile] = field(default_factory=list)


class OnvifClient:
    def __init__(
        self, xaddr: str, username: str | None, password: str | None, timeout: float = 6.0
    ):
        if urlsplit(xaddr).scheme not in ("http", "https"):
            raise SourceError("invalid", "ONVIF address must be an http(s) URL")
        self.xaddr = xaddr
        self._username = username or ""
        self._password = password or ""
        self._clock_offset = timedelta(0)
        self._http = httpx.Client(timeout=timeout, verify=False)  # cameras use self-signed certs
        self._http_auth: httpx.Auth | None = None

    def close(self) -> None:
        self._http.close()

    def _security_header(self) -> str:
        if not self._username:
            return ""
        nonce = os.urandom(16)
        created = (datetime.now(UTC) + self._clock_offset).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        digest = base64.b64encode(
            hashlib.sha1(nonce + created.encode() + self._password.encode()).digest()
        ).decode()
        user = self._username.replace("&", "&amp;").replace("<", "&lt;")
        return f"""<s:Header><Security s:mustUnderstand="1"
 xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
<UsernameToken><Username>{user}</Username>
<Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest}</Password>
<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{base64.b64encode(nonce).decode()}</Nonce>
<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">{created}</Created>
</UsernameToken></Security></s:Header>"""

    def call(self, url: str, body: str, authenticate: bool = True) -> ET.Element:
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
            f"{self._security_header() if authenticate else ''}<s:Body>{body}</s:Body></s:Envelope>"
        )
        try:
            response = self._http.post(
                url, content=envelope, headers={"Content-Type": _SOAP}, auth=self._http_auth
            )
            if response.status_code == 401 and self._http_auth is None and self._username:
                self._http_auth = httpx.DigestAuth(self._username, self._password)
                response = self._http.post(
                    url, content=envelope, headers={"Content-Type": _SOAP}, auth=self._http_auth
                )
        except httpx.TimeoutException:
            raise SourceError(
                "timeout", "The camera's ONVIF service didn't answer in time"
            ) from None
        except httpx.HTTPError as e:
            raise SourceError("unreachable", f"Couldn't reach the ONVIF service: {e}") from None

        if response.status_code == 401:
            raise SourceError("auth", "ONVIF login rejected: check username and password")
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError:
            raise SourceError(
                "invalid", f"Not an ONVIF response (HTTP {response.status_code})"
            ) from None
        if (fault := _first(root, "Fault")) is not None:
            detail = " ".join(t.strip() for t in fault.itertext() if t.strip())
            if "NotAuthorized" in detail or response.status_code == 401:
                raise SourceError("auth", "ONVIF login rejected: check username and password")
            raise SourceError("invalid", f"ONVIF error: {detail[:200]}")
        return root

    def sync_clock(self) -> None:
        """WS-Security timestamps must match the camera's clock, which is often off."""
        try:
            root = self.call(
                self.xaddr,
                '<GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/>',
                authenticate=False,
            )
        except SourceError as e:
            if e.code in ("unreachable", "timeout"):
                raise
            return
        utc = _first(root, "UTCDateTime")
        if utc is None:
            return
        try:
            parts = {
                k: int(_text(utc, k) or 0)
                for k in ("Year", "Month", "Day", "Hour", "Minute", "Second")
            }
            camera_now = datetime(
                parts["Year"],
                parts["Month"],
                parts["Day"],
                parts["Hour"],
                parts["Minute"],
                parts["Second"],
                tzinfo=UTC,
            )
        except ValueError:
            return
        self._clock_offset = camera_now - datetime.now(UTC)

    def streams(self) -> DeviceStreams:
        self.sync_clock()
        info = self.call(
            self.xaddr, '<GetDeviceInformation xmlns="http://www.onvif.org/ver10/device/wsdl"/>'
        )
        result = DeviceStreams(manufacturer=_text(info, "Manufacturer"), model=_text(info, "Model"))

        caps = self.call(
            self.xaddr,
            '<GetCapabilities xmlns="http://www.onvif.org/ver10/device/wsdl"><Category>Media</Category></GetCapabilities>',
        )
        media = _first(caps, "Media")
        media_url = _text(media, "XAddr") or self.xaddr

        profiles = self.call(
            media_url, '<GetProfiles xmlns="http://www.onvif.org/ver10/media/wsdl"/>'
        )
        for el in (e for e in profiles.iter() if _local(e.tag) == "Profiles"):
            token = el.get("token")
            if not token:
                continue
            encoder = _first(el, "VideoEncoderConfiguration")
            resolution = _first(encoder, "Resolution") if encoder is not None else None
            uri = self.call(
                media_url,
                '<GetStreamUri xmlns="http://www.onvif.org/ver10/media/wsdl"><StreamSetup>'
                '<Stream xmlns="http://www.onvif.org/ver10/schema">RTP-Unicast</Stream>'
                '<Transport xmlns="http://www.onvif.org/ver10/schema"><Protocol>RTSP</Protocol></Transport>'
                f"</StreamSetup><ProfileToken>{token}</ProfileToken></GetStreamUri>",
            )
            result.profiles.append(
                Profile(
                    token=token,
                    name=_text(el, "Name"),
                    encoding=_text(encoder, "Encoding") if encoder is not None else None,
                    width=int(w) if (w := _text(resolution, "Width")) else None,
                    height=int(h) if (h := _text(resolution, "Height")) else None,
                    uri=_text(uri, "Uri"),
                )
            )
        return result
