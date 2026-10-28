# Configuration

The backend reads every setting from an environment variable with the `ZW_` prefix, or from
`backend/.env` (start from [`backend/.env.example`](../backend/.env.example)). Environment
variables win over the file. All settings are optional except `ZW_SECRET_KEY` outside local
development. The source of truth is [`backend/app/config.py`](../backend/app/config.py).

Durations are in seconds unless the name says otherwise. Booleans accept `true`/`false`
(or `1`/`0`).

## Storage and server

| Variable | Default | |
|---|---|---|
| `ZW_DATABASE_URL` | `sqlite:///./zonewatch.db` | Any SQLAlchemy URL. Postgres: `postgresql+psycopg://user:pass@host/db` (needs `uv sync --extra postgres`). The schema migrates itself on startup |
| `ZW_CORS_ORIGINS` | `["http://localhost:5173"]` | JSON list. Only matters if the frontend is served from another origin; the shipped setups proxy `/api` on the same origin |

## Accounts and sessions

| Variable | Default | |
|---|---|---|
| `ZW_SECRET_KEY` | a development key | **Required in production** (`openssl rand -hex 32`). Signs session tokens and derives the key that encrypts stored camera passwords, so changing it signs everyone out and makes stored camera passwords unreadable |
| `ZW_SESSION_COOKIE` | `zw_session` | Cookie name |
| `ZW_SESSION_TTL_HOURS` | `168` | Session lifetime (7 days) |
| `ZW_COOKIE_SECURE` | `false` | Set `true` behind HTTPS |

## Detection

| Variable | Default | |
|---|---|---|
| `ZW_DETECTOR` | `ultralytics` | `ultralytics` (YOLO), `rfdetr`, or `fake` (detects nothing: for tests and UI work without ML) |
| `ZW_DETECTOR_MODEL` | (backend default) | Ultralytics: a weights name or path (default `models/yolo26n.pt`, downloaded on first use). RF-DETR: `nano`, `small`, `medium`, `base` or `large` |
| `ZW_CONFIDENCE` | `0.4` | Minimum detection confidence. The demo uses `0.3` |
| `ZW_DETECTOR_IMGSZ` | `640` | Ultralytics inference size. `1280` finds small, distant people (in one frame of the demo's plaza, 5 people at 640 and 52 at 1280, at confidence 0.25) at roughly twice the cost |
| `ZW_DEVICE` | auto | `cpu`, `cuda:0`, or `mps` (Apple GPU) |

Install the detector you use: `uv sync --extra yolo`, `--extra rfdetr`, or both.

**Licensing:** Ultralytics YOLO is **AGPL-3.0**, so running it in a network service obliges
you to publish your source, unless you hold an Ultralytics enterprise license. RF-DETR is
**Apache-2.0**; use `ZW_DETECTOR=rfdetr` if that matters.

## Camera workers

| Variable | Default | |
|---|---|---|
| `ZW_START_WORKERS` | `true` | `false` runs the API without processing any camera |
| `ZW_MAX_FPS` | `15` | Processing cap per camera. Counting rarely needs more than 5 |
| `ZW_FRAME_WIDTH` | `960` | Frames are downscaled to this width before inference and streaming |
| `ZW_JPEG_QUALITY` | `80` | Quality of the annotated JPEGs for video |
| `ZW_OPEN_TIMEOUT_S` | `8` | Give up connecting to a camera (and reading its headers) after this long |
| `ZW_READ_TIMEOUT_S` | `8` | Reconnect when no frame arrives for this long |
| `ZW_RECONNECT_DELAY_S` | `2` | First retry delay; it doubles on each failure… |
| `ZW_RECONNECT_MAX_DELAY_S` | `30` | …up to this |
| `ZW_FLUSH_INTERVAL_S` | `60` | How often per-minute counts are written to the database |

## Live video

Video is the only cost that grows with every viewer, so these exist for public deployments.
None of them affect counts, alerts or incidents. See
[Live video delivery](architecture/live-video.md#pausing-and-capping-video).

| Variable | Default | |
|---|---|---|
| `ZW_STREAM_FPS` | `ZW_MAX_FPS` | Output rate of video to browsers |
| `ZW_MAX_VIDEO_VIEWERS` | unlimited | Concurrent video connections (tile sockets and MJPEG streams). Above it, viewers get "at capacity" |
| `ZW_VIDEO_SESSION_MAX_S` | off | Close video connections after this long; the viewer clicks to resume |
| `ZW_VIDEO_IDLE_TIMEOUT_S` | off | Browsers pause video after this long without input |

## Incidents

| Variable | Default | |
|---|---|---|
| `ZW_INCIDENT_OPEN_AFTER_S` | `1` | An alert must hold this long to open an incident |
| `ZW_INCIDENT_CLOSE_AFTER_S` | `3` | A danger zone must be clear this long to close one |
| `ZW_OCCUPANCY_INCIDENT_CLOSE_AFTER_S` | `15` | The same for occupancy cameras, whose counts hover around their limit |
| `ZW_INCIDENTS_KEPT_PER_CAMERA` | `200` | Older incidents (and their snapshots) are deleted |

## Metrics

| Variable | Default | |
|---|---|---|
| `ZW_METRICS` | `off` | `emf`: write CloudWatch Embedded Metric Format lines to stdout ([what's in them](aws/monitoring.md)) |
| `ZW_METRICS_INTERVAL_S` | `60` | How often |

## Demo mode

| Variable | Default | |
|---|---|---|
| `ZW_DEMO_MODE` | `false` | No login (everyone is the demo user), scenario cameras are seeded in the background, and only phone/browser cameras can be added. See [the demo](demo.md) |
| `ZW_DEMO_VIDEO_DIR` | `data/demo-videos` | Where the trimmed scenario clips are cached. `/data/demo-videos` in Docker (the data volume) |
| `ZW_DEMO_MAX_BROWSER_CAMERAS` | `4` | Phone cameras visitors may add |
| `ZW_DEMO_PASSWORD` | `demo-password` | Password of `demo@example.com`, for signing in when demo mode is off |

## Frontend and Docker

These aren't backend settings, but they come up when running the stack.

| Variable | Where | |
|---|---|---|
| `VITE_BACKEND_URL` | `npm run dev` | Where Vite proxies `/api` to (default `http://localhost:8000`), e.g. when port 8000 is taken |
| `ZW_DEV_LAN=1` | `npm run dev:lan` sets it | Serve the dev server over HTTPS on the LAN, so phones can use their camera |
| `DETECTOR_EXTRAS` | `docker compose build` | Detectors to install in the image: `yolo` (default), `rfdetr`, or `"yolo rfdetr"` |

`docker-compose.yml` requires `ZW_SECRET_KEY` and passes a few common settings through. With
`docker-compose.gpu.yml` the backend receives the whole `.env` file, so any `ZW_*` setting can
be set there.

## Presets

**Local development:** nothing is required. Add `ZW_DEVICE=mps` on a Mac.

**The demo, locally** ([details](demo.md)):

```bash
ZW_DEMO_MODE=true ZW_DETECTOR_IMGSZ=1280 ZW_CONFIDENCE=0.3 ZW_STREAM_FPS=8
```

**The public demo on AWS** (written to `.env` by the instance's boot script, see
[Deploying](aws/deploy.md#boot-sequence-user-data)):

```bash
ZW_DEMO_MODE=true ZW_DEVICE=cuda:0 ZW_DETECTOR_IMGSZ=1280 ZW_CONFIDENCE=0.3 ZW_STREAM_FPS=8
ZW_MAX_VIDEO_VIEWERS=40 ZW_VIDEO_SESSION_MAX_S=1800 ZW_VIDEO_IDLE_TIMEOUT_S=600
ZW_METRICS=emf ZW_COOKIE_SECURE=true ZW_DEMO_VIDEO_DIR=/data/demo-videos
```
