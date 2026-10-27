# Development

How the code is laid out, how to run the checks, how the tests work, and where to extend it.
The design behind the code is in the [system design](architecture/README.md).

## Repository layout

```
backend/                     FastAPI · SQLAlchemy 2 · Alembic · uv
  app/main.py                app factory, startup (migrations, demo seeding, metrics)
  app/config.py              every CC_* setting
  app/api/                   HTTP + WebSocket routes: auth, cameras, stream (status, frames,
                             MJPEG), incidents, analytics, publish, onvif, demo_api
  app/vision/
    sources/                 one module per source type; reader.py keeps the newest frame
                             and reconnects; errors.py maps failures to codes + hints
    detectors/               ultralytics.py · rfdetr.py · fake.py, behind one locked detector
    counter.py               zone membership by foot position, unique entries per track
    worker.py                one thread per camera: detect → track → count → annotate
    alerts.py                alert limit per mode, the IncidentTracker state machine (pure)
    manager.py               workers, status snapshots, count persistence, incident monitor
    stats.py                 per-minute aggregation of counts
  app/demo.py                demo scenarios: footage download/trim, seeding, reset
  app/metrics.py             CloudWatch Embedded Metric Format publisher
  app/viewers.py             the video viewer cap
  app/onvif.py               WS-Discovery and ONVIF media profiles
  app/migrations/            Alembic, applied automatically on startup
  tests/                     pytest, incl. local fake cameras (servers.py)
frontend/                    React 19 · TypeScript · Vite · Tailwind 4 · TanStack Query · Recharts
  src/pages/                 Live, Cameras, CameraEdit, Incidents, Analytics, Publish, Auth
  src/components/            Shell (nav, alerts), ZoneEditor, SourceEditor, PublishPanel, ui
  src/lib/                   api.ts (typed client), live.tsx (status socket), frames.ts
                             (tile video socket), video.ts (pause/cap gate), config.ts
infra/                       AWS CDK (Python): the demo stack and the GitHub deploy roles
docs/                        this documentation
docker-compose*.yml          local Docker; GPU and AWS logging overrides
.github/workflows/           ci.yml (checks), deploy.yml (AWS, with approval)
```

## Checks

```bash
cd backend  && uv run pytest && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
cd infra    && uv run ruff check . && uv run ruff format --check . && npx aws-cdk@2 synth --quiet
```

CI runs exactly these three groups on every push and pull request
([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)). The infra synth runs the cdk-nag
AWS Solutions checks, and any finding that hasn't been explicitly acknowledged fails it.

## Tests

**Backend** (pytest, about 90 tests, ~30 s):

| Module | Covers |
|---|---|
| `test_sources.py` | Every source type against **real local servers**: MJPEG and snapshot cameras with Basic/Digest auth, HLS from `ffmpeg`, password-protected RTSP from MediaMTX. Error classification (auth, not found, unreachable, timeout) |
| `test_camera_sources_api.py` | Source handling through the API: credential splitting and storage, probes, browser publishing, a fake ONVIF camera (incl. clock skew), the credentials migration |
| `test_counter.py` | Zone membership by foot position, unique entries per track, unconfirmed tracks |
| `test_alerts.py` | The alert rule per mode and the incident state machine, on a fake clock |
| `test_pipeline.py` | End to end: a generated video through worker → MJPEG/WebSockets → DB → analytics; worker restarts; alert limits; incidents; the frames socket |
| `test_analytics.py` | Per-minute aggregation and bucketing |
| `test_api.py` | Sign-up, login and sessions, camera CRUD, zone validation, and that other users' cameras are unreachable |
| `test_demo_mode.py` | No login; only browser cameras; scenario protection and reset |
| `test_video_limits.py` | Viewer cap, session expiry, metrics format, detector stats |
| `test_detectors.py` | The real models on a sample image. Opt-in: `CC_RUN_MODEL_TESTS=1 uv run --extra yolo --extra rfdetr pytest tests/test_detectors.py` |

- Tests use the **fake detector** and a temporary SQLite database (see `tests/conftest.py`).
  Tests that need people monkeypatch the fake's `detect`.
- Tests that need `ffmpeg` or `mediamtx` skip themselves when the tool is missing. CI
  installs both.

**Frontend** (Vitest, Node environment): pure logic only, such as zone geometry, source-form
helpers, and the video pause gate with fake timers. Anything involving the DOM is kept out of
the tested modules.

## Database migrations

The schema is managed with Alembic and migrated automatically on startup (`init_db()`).
After changing the models in `app/db.py`:

```bash
cd backend && uv run alembic revision --autogenerate -m "what changed"
```

Review the generated file in `app/migrations/versions/`. SQLite can't alter most columns in
place, so migrations use batch mode.

## Extending it

| To add | Do this |
|---|---|
| **A source type** | Implement the `FrameSource` protocol (`app/vision/sources/base.py`: `info`, `read()`, `close()`, raising `SourceError`), add it to `open_source()`, to `Kind`/`validate()` in `spec.py` and `SourceKind` in `app/schemas.py`, then to `KINDS` in `frontend/src/components/SourceEditor.tsx` |
| **A detector** | Implement `Detector` (`app/vision/detectors/__init__.py`: `name`, `detect(frame) -> sv.Detections` with people only) and add it to `build_detector()` and the `detector` setting's `Literal` in `app/config.py` |
| **An alert rule** | Change `alert_limit()` in `app/vision/alerts.py` (pure, tested in `test_alerts.py`). Every consumer reads `over_limit` from the manager's snapshot |
| **A notifier** (email, SMS, webhook) | Hook the incident *opened* event in `CameraManager._record`; it's the single place alerts are decided |
| **A metric** | Add it to `MetricsCollector.collect()` in `app/metrics.py`, then a graph or alarm in `infra/crowdcounting_infra/monitoring.py` |
| **A setting** | Add it to `app/config.py` and to [Configuration](configuration.md) |

## Conventions

- Python 3.12+, typed, `ruff` with a 100-character line length. Frontend: strict TypeScript
  and ESLint; colors are theme tokens in `src/index.css`.
- Comments explain *why*. Decisions that shape the system get a record in
  [`docs/adr/`](adr/README.md).
- Pure logic is kept apart from I/O (`counter.py`, `alerts.py`, `stats.py`, `video.ts`) so it
  can be tested directly.

## Security notes for self-hosting

Camera sources are opened **by the server**, so a user can point one at any URL or file the
server can reach (including through **Test connection** and ONVIF lookups). Publish links work
like stream keys: anyone holding one can stream to that camera until it's replaced. That's
fine for a self-hosted tool where every user is trusted. Restrict sources before exposing
sign-up to the public internet. `CC_DEMO_MODE` does exactly that for the public demo
([Security](architecture/security.md)).
