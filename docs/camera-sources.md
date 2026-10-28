# Camera sources

Every camera is a *source* the server reads frames from, except phone and laptop cameras,
which push frames to the server. This page covers each type, how to find a camera's URL, and
how connections are kept alive. The connection internals are in
[Failure modes](architecture/reliability.md).

Add cameras under **Cameras → Add camera**, pick a source type, and press **Test connection**
before saving. It shows a live preview frame with the resolution, codec and time to first
frame, or a specific error (wrong password, wrong path, unreachable, timed out) with a hint.

| Type | Examples | Notes |
|---|---|---|
| Network stream | `rtsp://192.168.1.64:554/Streaming/Channels/102`, `rtsps://…`, `rtmp://…`, `srt://…`, `http://…/live.m3u8`, `http://phone:8080/video` | Decoded with FFmpeg (PyAV). RTSP defaults to **TCP** transport (UDP/auto selectable) to avoid smeared frames over Wi-Fi and VPNs. |
| Snapshot URL | `http://cam/cgi-bin/snapshot.cgi` | For cameras that only serve still images; polled every 500 ms by default. Basic or Digest auth, picked from the camera's challenge. |
| Phone / browser | publish link + QR code | Open the link on any device and tap **Start camera**; frames stream over a WebSocket. A second device takes over from the first. |
| USB webcam | `0`, `/dev/video0` | A camera attached to the server. |
| Video file | `/videos/lobby.mp4` | Loops at its native frame rate, for demos. |

**Finding the URL.** Use **Build from brand template** (Hikvision, Dahua/Amcrest, Reolink, Axis,
Tapo, UniFi Protect, Hanwha, Foscam, …), or **Find on network (ONVIF)** to scan the LAN and
pick a stream profile from the camera itself. For counting, a camera's lower-resolution
*sub-stream* is usually plenty and much lighter on bandwidth and CPU.

**Credentials** go in their own fields; any `user:pass@` pasted into a URL is moved there.
Passwords are encrypted at rest with a key derived from `ZW_SECRET_KEY` and are never sent
back to the browser. Changing `ZW_SECRET_KEY` makes stored camera passwords unreadable, and
those cameras report an auth error until their password is re-entered.

**Resilience.** Every connection has open and read timeouts (`ZW_OPEN_TIMEOUT_S`,
`ZW_READ_TIMEOUT_S`), so a hung camera can't freeze its worker. Failed or dropped streams
reconnect with exponential backoff, up to `ZW_RECONNECT_MAX_DELAY_S`. Each camera's page shows
live stream health: state, last error with a hint, resolution, codec and reconnect count.

**Phones need HTTPS.** Browsers only allow camera access on secure pages (or `localhost`).
In development run `npm run dev:lan`, which serves `https://<your-LAN-IP>:5173` with a
self-signed certificate (accept the warning once on the phone). Set the publish panel's
*Base URL* to that address so the QR code points to it. In production, put the app behind
HTTPS.

**ONVIF discovery** uses multicast, which doesn't cross routers or Docker's bridge network:
run the backend with `network_mode: host` to scan from a container. On macOS the app that
runs the backend needs *Local Network* permission (System Settings → Privacy & Security). If
discovery is blocked, you can still enter a camera's IP by hand.

## Source options

Each appears in the camera editor under its source type, and as `options` in the
[API](api.md#cameras):

| In the editor | API option | Applies to | |
|---|---|---|---|
| RTSP transport | `rtsp_transport` | Network streams | `tcp` (default), `udp`, or `auto` |
| Accept the camera's self-signed certificate | `insecure_tls` | HTTPS streams and snapshots | Common on cameras' built-in web servers |
| Poll interval | `snapshot_interval_ms` | Snapshot URLs | 100–60000 ms (default 500, about 2 frames per second) |
| Capture width | `width` | USB webcams | Blank = the webcam's default |

## In demo mode

The public demo only accepts **Phone / browser** cameras. Every other type makes the server
connect to an address or file a visitor chose, so those types, **Test connection** on them,
and ONVIF discovery are refused ([why](adr/0006-public-demo-mode.md)).
