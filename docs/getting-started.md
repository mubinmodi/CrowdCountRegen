# Getting started

This gets CrowdCounting running on your machine, from a plain local setup to Docker. For the
seven-scenario demo with no login, see [the demo](demo.md). For AWS, see [aws/](aws/README.md).

## Requirements

- **Python 3.12–3.13** with [uv](https://docs.astral.sh/uv/)
- **Node 22+** with npm 11
- Optional: an NVIDIA GPU (Linux) or an Apple-silicon Mac for faster detection. On a CPU,
  keep `CC_MAX_FPS` and the number of cameras low.
- Only for some tests: `ffmpeg` and [MediaMTX](https://mediamtx.org) (`brew install ffmpeg
  mediamtx`)

## Run it locally

```bash
# 1. Backend: http://localhost:8000, interactive API docs at /docs
cd backend
uv sync --extra yolo          # or --extra rfdetr, or both
uv run uvicorn app.main:app --reload --port 8000 --timeout-graceful-shutdown 3
```

```bash
# 2. Frontend: http://localhost:5173, proxies /api to the backend
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and create an account. The YOLO weights (about 5 MB) download on
first use into `backend/models/`, so the first camera takes a few seconds longer to start.

To start with cameras already set up, seed the demo account first:

```bash
cd backend && uv run python -m app.seed    # downloads and trims ~280 MB of sample footage
```

Then sign in as `demo@example.com` / `demo-password`, or run the backend with
`CC_DEMO_MODE=true` to skip the login entirely.

## Add your first camera

1. **Cameras → Add camera**, give it a name, and pick a source type. Every type is described
   in [Camera sources](camera-sources.md).
2. Press **Test connection**. You get a preview frame with the resolution, codec and time to
   first frame, or a specific error with a hint (wrong password, wrong path, unreachable,
   timed out).
3. Choose a **mode**: *Occupancy* (alert above a number of people) or *Danger zone* (alert
   when anyone enters). Set the limit, then **Add camera**.
4. On the camera's page, **draw the zone** on a live frame: click to add points, drag to move
   them, double-click to remove one. With no zone, the whole frame counts.
5. Go to the **Live wall**. The [user guide](user-guide.md) explains each screen.

## Use a phone as a camera

Add a camera of type **Phone / browser** and open its publish link (or scan the QR code) on
the phone. Browsers only allow camera access on HTTPS pages or on `localhost`, so for a phone
on your network run the frontend with:

```bash
cd frontend && npm run dev:lan
```

This serves `https://<your-LAN-IP>:5173` with a self-signed certificate (accept the warning
once on the phone). Set the publish panel's **Base URL** to that address so the QR code points
to it.

## Docker

```bash
export CC_SECRET_KEY=$(openssl rand -hex 32)
docker compose up --build        # → http://localhost:8080
```

- Choose the detector with `DETECTOR_EXTRAS="rfdetr" CC_DETECTOR=rfdetr docker compose up --build`.
- Put video files in `./videos/` and use `/videos/<file>` as a camera's source.
- The images use PyPI's PyTorch wheels, which include CUDA on Linux. On a host with an NVIDIA
  GPU and nvidia-container-toolkit, add the GPU override:
  `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build`. It also passes
  your whole `.env` file to the backend, so any `CC_*` setting works there.
- ONVIF discovery uses multicast, which can't leave Docker's bridge network. To scan for
  cameras from the container, use `network_mode: host` (see the comment in
  `docker-compose.yml`).

## Configure it

Every setting is a `CC_*` environment variable or a line in `backend/.env`; the full list is
in [Configuration](configuration.md). The ones you're most likely to need:

| Variable | Why |
|---|---|
| `CC_SECRET_KEY` | Required anywhere but your laptop |
| `CC_DEVICE` | `mps` on a Mac, `cuda:0` with an NVIDIA GPU |
| `CC_DETECTOR_IMGSZ` | `1280` for wide shots with small, distant people |
| `CC_MAX_FPS` | Lower it (e.g. `5`) on a CPU or with many cameras |
| `CC_DATABASE_URL` | Postgres instead of SQLite |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `address already in use` on port 8000 | Something else uses it. Run the backend on `--port 8001` and the frontend with `VITE_BACKEND_URL=http://localhost:8001 npm run dev` |
| `objc: Class AVFFrameReceiver is implemented in both …` on macOS | OpenCV and PyAV each bundle FFmpeg's device library. Harmless warning |
| `CC_SECRET_KEY is not set; using an insecure development key` | Expected locally. Set it everywhere else |
| A camera stays *connecting* or shows an error | Open the camera: **Stream health** shows the error code and a hint. Sources reconnect by themselves with backoff |
| Very low FPS with several cameras | All cameras share one detector. Use a GPU (`CC_DEVICE`), lower `CC_MAX_FPS`, or keep `CC_DETECTOR_IMGSZ` at 640 ([why](architecture/performance.md)) |
| ONVIF finds nothing on macOS | The app running the backend needs *Local Network* permission (System Settings → Privacy & Security). You can always enter the camera's IP by hand |
| The phone can't open its camera | The page isn't HTTPS. Use `npm run dev:lan`, or the HTTPS deployment |
