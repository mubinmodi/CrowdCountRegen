# CrowdCounting

Real-time people counting for IP cameras, with per-camera counting zones, tracking-based
unique-visitor counts, construction-site danger zones, an incident log, and live and
historical analytics.

**Try the demo:** `CC_DEMO_MODE=true` opens straight onto seven live scenarios (road works,
an excavator's swing radius, an excavation edge, a plaza, a metro platform, a store aisle and
a lobby) with no login. See [docs/demo.md](docs/demo.md).

![demo](https://github.com/mubinmodi/Crowdcounting/assets/47493706/e1a5d00f-e6cf-4162-b5bb-e5b37161cd80)

Originally built as an undergraduate project at M.H. Saboo Siddik College of Engineering,
Mumbai (Dept. of Information Technology) by **Mubin Modi, Zaid Marouf and Anvay Wankhede**,
supervised by **Dr. Shabina Sayed**. Version 2 is a full rewrite on a modern stack; the
original write-up is in [docs/original-project.md](docs/original-project.md).

## Features

- **Any live camera**: RTSP/RTSPS, RTMP, SRT, HLS and HTTP MJPEG streams; snapshot-only
  cameras (Basic/Digest auth); USB webcams; video files; and any phone or laptop camera
  through a publish link, with no app to install. See [Camera sources](#camera-sources).
- **Pluggable detector**: [Ultralytics YOLO](https://docs.ultralytics.com) (default: YOLO26n)
  or Roboflow [RF-DETR](https://github.com/roboflow/rf-detr), switchable via one setting.
- **Counting zones**: draw a polygon on a live frame. A person counts when their feet are
  inside it, which avoids double-counting areas covered by more than one camera (the
  original project's "selective detection").
- **Tracking**: ByteTrack (from Roboflow [`trackers`](https://github.com/roboflow/trackers))
  gives each person an ID, so **unique visitors** are counted once, not once per frame.
- **Danger zones**: the same zone counting with a different rule: anyone inside (or more
  than an allowed number, e.g. a banksman) is an **intrusion**. Danger-zone cameras are drawn
  as barrier tape, with intruders boxed in red.
- **Incidents**: alerts become debounced incidents with a start, an end, a peak, and the
  annotated frame that triggered them. Debouncing filters out one-frame false detections and
  momentary occlusions.
- **Live dashboard**: annotated video per camera (all tiles over one WebSocket, full MJPEG
  for an enlarged view), current occupancy, alerts and a rolling chart.
- **Analytics**: occupancy (average/peak) and visitor entries stored per minute, browsable
  over 1 hour to 30 days, per camera or combined.
- **Public demo mode**: no login, seeded scenarios, and only push sources (phone cameras),
  so the server never connects to an address a visitor typed in.
- **Accounts**: Argon2-hashed passwords, httpOnly session cookies, and every camera, stream
  and statistic scoped to its owner.

## Architecture

```
frontend/  React 19 + TypeScript + Vite + Tailwind 4, TanStack Query, Recharts
backend/   FastAPI · SQLAlchemy 2 (SQLite by default, Postgres optional)
           app/vision/sources/     one module per source type + reader with reconnect/backoff
           app/vision/worker.py    one thread per camera: detect → track → count → annotate
           app/vision/alerts.py    alert limits per mode + the incident state machine (pure)
           app/vision/manager.py   worker lifecycle, status snapshots, counts, incident monitor
           app/vision/detectors/   ultralytics.py · rfdetr.py · fake.py (no-ML, for tests)
           app/demo.py             demo scenarios: footage download/trim, seeding, reset
infra/     AWS CDK (Python): one GPU instance behind CloudFront
docs/      architecture.md (system design) · adr/ · demo.md · deployment-aws.md
```

The full system design, with diagrams, the concurrency model, measured performance, failure
modes, the security model and a multi-node scaling path, is in
[docs/architecture.md](docs/architecture.md), with the decisions behind it in
[docs/adr/](docs/adr/).

All cameras share one detector instance. Inference is serialized with a lock, which on a
single GPU is about as fast as running in parallel. Each camera runs at most `CC_MAX_FPS`
(default 15) and drops stale frames rather than falling behind a live stream.

## Quick start (local)

Requirements: Python 3.12–3.13 with [uv](https://docs.astral.sh/uv/), and Node 22+ with npm 11.

```bash
# 1. Backend (http://localhost:8000, API docs at /docs)
cd backend
uv sync --extra yolo          # or --extra rfdetr, or both
uv run python -m app.seed     # optional: demo account + 7 scenario cameras (downloads ~280 MB)
uv run uvicorn app.main:app --reload --port 8000 --timeout-graceful-shutdown 3
```

```bash
# 2. Frontend (http://localhost:5173, proxies /api to the backend)
cd frontend
npm install
npm run dev
```

The seed script creates `demo@example.com` / `demo-password` with the seven demo scenario
cameras ([docs/demo.md](docs/demo.md)), downloading and trimming their clips on first run.
Add `CC_DEMO_MODE=true` to skip the login entirely. Model weights download automatically on first use:
YOLO weights go to `backend/models/` and RF-DETR weights to `~/.roboflow/`.

## Camera sources

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
Passwords are encrypted at rest with a key derived from `CC_SECRET_KEY` and are never sent
back to the browser. Changing `CC_SECRET_KEY` makes stored camera passwords unreadable, and
those cameras report an auth error until their password is re-entered.

**Resilience.** Every connection has open and read timeouts (`CC_OPEN_TIMEOUT_S`,
`CC_READ_TIMEOUT_S`), so a hung camera can't freeze its worker. Failed or dropped streams
reconnect with exponential backoff, up to `CC_RECONNECT_MAX_DELAY_S`. Each camera's page shows
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

## Docker

```bash
export CC_SECRET_KEY=$(openssl rand -hex 32)
docker compose up --build        # → http://localhost:8080
```

Choose the detector with `DETECTOR_EXTRAS="rfdetr" CC_DETECTOR=rfdetr docker compose up --build`.
Put video files in `./videos/` and use `/videos/<file>` as the camera source. The images use
PyPI's PyTorch wheels, which include CUDA on Linux. Uncomment the `deploy` block in
`docker-compose.yml` to use an NVIDIA GPU.

## Configuration

Environment variables (or `backend/.env`; see [`backend/.env.example`](backend/.env.example)):

| Variable | Default | |
|---|---|---|
| `CC_SECRET_KEY` | dev key | **Required in production.** Signs session tokens. |
| `CC_DATABASE_URL` | `sqlite:///./crowdcounting.db` | e.g. `postgresql+psycopg://…` (`uv sync --extra postgres`) |
| `CC_DETECTOR` | `ultralytics` | `ultralytics`, `rfdetr`, or `fake` |
| `CC_DETECTOR_MODEL` | `models/yolo26n.pt` / `nano` | Ultralytics weights name/path, or RF-DETR size (`nano`…`large`) |
| `CC_CONFIDENCE` | `0.4` | Minimum detection confidence |
| `CC_DETECTOR_IMGSZ` | `640` | Ultralytics inference size; 1280 finds small, distant people (the demo uses it) |
| `CC_DEVICE` | auto | `cpu`, `cuda:0`, `mps` |
| `CC_MAX_FPS` | `15` | Processing cap per camera |
| `CC_FRAME_WIDTH` | `960` | Frames are downscaled to this width |
| `CC_STREAM_FPS` | `CC_MAX_FPS` | Live video output rate; lower it to save bandwidth |
| `CC_INCIDENT_OPEN_AFTER_S` | `1` | An alert must hold this long to open an incident |
| `CC_INCIDENT_CLOSE_AFTER_S` / `CC_OCCUPANCY_INCIDENT_CLOSE_AFTER_S` | `3` / `15` | Clear this long to close a danger-zone / occupancy incident |
| `CC_DEMO_MODE` | `false` | Public demo: no login, seeded scenarios, phone cameras only |
| `CC_DEMO_VIDEO_DIR` | `data/demo-videos` | Where scenario clips are cached (`/data/demo-videos` in Docker) |
| `CC_COOKIE_SECURE` | `false` | Set `true` behind HTTPS |
| `CC_OPEN_TIMEOUT_S` / `CC_READ_TIMEOUT_S` | `8` / `8` | Give up connecting / waiting for a frame, then reconnect |
| `CC_RECONNECT_DELAY_S` / `CC_RECONNECT_MAX_DELAY_S` | `2` / `30` | First retry delay, and the cap for exponential backoff |

### Licensing note on detectors

Ultralytics YOLO is **AGPL-3.0**, so using it in a network service obliges you to publish your
source, unless you hold an Ultralytics enterprise license. RF-DETR is **Apache-2.0**. Set
`CC_DETECTOR=rfdetr` if that matters for your deployment.

## Development

```bash
cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

`CC_RUN_MODEL_TESTS=1 uv run --extra yolo --extra rfdetr pytest tests/test_detectors.py`
also runs both real models against a sample image.

Source tests run against real local servers: MJPEG and snapshot cameras (Basic/Digest),
HLS from `ffmpeg`, and password-protected RTSP from [MediaMTX](https://mediamtx.org)
(`brew install mediamtx ffmpeg`). Tests skip automatically when those tools are missing.

The schema is managed with Alembic and migrated automatically on startup. After changing the
models, create a migration with `uv run alembic revision --autogenerate -m "…"` in `backend/`.

### Security notes

Camera sources are opened by the server, so a user can point one at any URL or file the server
can reach (including through **Test connection** and ONVIF lookups). Publish links work like
stream keys: anyone holding one can stream to that camera until it's replaced. That's fine for a self-hosted tool where every user is trusted. Restrict sources
before exposing sign-up to the public internet. `CC_DEMO_MODE` does exactly that for the
public demo: only phone cameras can be added, and probes and ONVIF lookups are refused
([ADR 0006](docs/adr/0006-public-demo-mode.md)).

## Deploying to AWS

`infra/` deploys the public demo to one NVIDIA T4 instance behind CloudFront (HTTPS, so phone
cameras work), with no SSH and a security group that only admits CloudFront. Steps, costs,
prerequisites (a G-instance quota and CloudFormation access) and the security model are in
[docs/deployment-aws.md](docs/deployment-aws.md).

## What changed from v1

| v1 (2021) | v2 |
|---|---|
| TensorFlow 2.3 RC, hand-ported YOLOv4, manual Darknet weight conversion | Ultralytics YOLO26 or RF-DETR, weights auto-download |
| Per-frame counts; boxes had to be fully inside a rectangle | ByteTrack IDs, unique-visitor counts, polygon zones on foot position |
| Flask + MongoDB, analytics never persisted | FastAPI + SQLAlchemy, per-minute history |
| Threads killed via `ctypes`, busy-wait loops | Cooperative stop events, condition variables |
| Werkzeug debugger exposed on LAN, hard-coded secret, unauthenticated GET-deletes | Auth on every route, ownership checks, httpOnly cookies |
| Hard-coded `http://<ip>:8080/video` (Android IP Webcam app), 720×480 | Any RTSP/RTMP/SRT/HLS/MJPEG/snapshot camera, ONVIF discovery, phone publishing without an app; resolution-independent zones |
| No tests, no CI | pytest + Vitest, ruff, ESLint, GitHub Actions, Docker |
