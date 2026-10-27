# The demo

Demo mode opens straight onto a live console with seven scenarios on looping sample footage:
three construction-site **danger zones** and four **occupancy** cameras. There's no login.
Visitors can redraw zones, change limits, switch modes and add their own phone as a live
camera, but can't point the server at any other source ([why](adr/0006-public-demo-mode.md)).

## Watch it

[![The demo in 70 seconds](media/demo-preview.gif)](media/demo.mp4)

[The full walkthrough](media/demo.mp4) (70 s, 1440×900) was recorded from this demo running
locally on an Apple-silicon Mac (YOLO26n at 1280 px on the GPU, about 4–5 FPS per camera). It
follows the walkthrough below. Captions and the cursor were added for the recording only.

## Run it locally

```bash
cd backend
uv sync --extra yolo
uv run python -m app.demo        # first time: downloads and trims the clips (~280 MB, 1–2 min)
CC_DEMO_MODE=true CC_DETECTOR_IMGSZ=1280 CC_CONFIDENCE=0.3 CC_STREAM_FPS=8 \
  uv run uvicorn app.main:app --port 8000
```

```bash
cd frontend && npm install && npm run dev     # http://localhost:5173
```

To try the public-demo cost controls locally, add `CC_VIDEO_IDLE_TIMEOUT_S=60`
(video pauses after a minute without input) or `CC_MAX_VIDEO_VIEWERS=0` (every viewer gets
"at capacity" while counts keep updating). On a Mac add `CC_DEVICE=mps` to use the GPU; expect 3–6 FPS per camera across seven cameras.
With an NVIDIA GPU, use `CC_DEVICE=cuda:0`. Without one, set `CC_DETECTOR_IMGSZ=640` and
`CC_MAX_FPS=5` to keep up, at the cost of missing most of the plaza's distant crowd. The
seeding step is optional: in demo mode the server does it in the background on first start,
and cameras appear on the wall as each clip becomes ready.

With Docker: `CC_SECRET_KEY=$(openssl rand -hex 32)` plus the same `CC_*` variables in a `.env`
file, then `docker compose up --build` and open http://localhost:8080. The AWS deployment is
in [aws/](aws/README.md).

## Scenarios

| Scenario | Mode | Zone and limit | What happens |
|---|---|---|---|
| **Road works · live traffic lane** | Danger zone | The carriageway, 0 allowed | A crew waits on the kerb (clear), then crosses: each crossing is an intrusion with 4–6 people, and it clears once they reach the far side |
| **Demolition · excavator swing radius** | Danger zone | The excavator's working area, 0 allowed | A worker hosing down dust stands inside the swing radius the whole time, so one incident stays open and its duration keeps growing |
| **Earthworks · excavation edge** | Danger zone | A strip along an open excavation, 0 allowed | Two engineers walk towards the edge and step into the strip near the end of each loop |
| **Public plaza · crowd capacity** | Occupancy | The central walkway, limit 32 | 20–40 people from a high angle; the alert comes and goes with the crowd. This is the scenario that needs `imgsz` 1280 |
| **Transit · metro platform** | Occupancy | Whole frame, limit 15 | A handheld walk down a busy platform as a train arrives |
| **Retail · aisle during restocking** | Occupancy | The aisle floor only, limit 1 | One shopper is fine; a second entering the aisle raises the alert |
| **Lobby · entrance zone** | Occupancy | The bottom half of an atrium, limit 13 | Steady foot traffic around the limit; shows how a zone splits overlapping camera views |

Footage: Pexels videos 7259509, 38817827 and 8964933 (Pexels license), and Roboflow's
supervision example videos. Clips are fetched at first boot, not stored in the repo
([ADR 0008](adr/0008-demo-footage-fetched-at-boot.md)).

## A five-minute walkthrough

1. **Live wall.** Two sections: *Site safety* and *Occupancy*. Point out that it's one
   detector and one tracker; a danger zone is just a zone whose limit is 0, drawn as barrier
   tape. Watch the road crew: the tile turns red with **INTRUSION** as they step off the kerb,
   and the top bar's alert count goes up.
2. **Open the excavator tile** (click it). The enlarged view streams full resolution and shows
   the allowed count, people who entered, a three-minute sparkline, and the scenario's
   description. Click **Incidents**.
3. **Incidents.** Each row has the frame that triggered it, the peak count and the duration.
   The excavator incident is still open and ticking; the road crossings are short, separate
   incidents. Explain the debounce: 1 s to open, 3 s of clear to close for danger zones, and
   15 s for occupancy so one busy spell is one incident
   ([ADR 0004](adr/0004-incidents-debounced-state-machine.md)).
4. **Change a rule live.** Open *Earthworks* → set **People allowed inside** to 2 → Save. The
   alert clears immediately, and the *Entered* count doesn't reset, because limits never
   restart the pipeline ([ADR 0003](adr/0003-alert-limits-outside-the-pipeline.md)). Then
   redraw the danger zone on the frame (click to add points, drag to move, double-click to
   delete) and save; the new zone is drawn on the next frame.
5. **Switch a mode.** Turn *Lobby* into a danger zone: same zone, same counts, different
   rules and UI.
6. **Go live with a phone.** Click **Use my phone** (or *Add camera*), save, scan the QR code
   with a phone, allow camera access, then make it a danger zone and walk into it. Phones need
   HTTPS, so this works on the AWS URL, or locally with `npm run dev:lan`.
7. **Analytics.** Per-minute occupancy and entries per camera or combined.
8. **Reset scenarios** on the banner puts every scenario's zone, mode and limit back.

Things worth saying about the design: newest-frame-only handoffs everywhere, so a slow camera
shows lower FPS but never falls behind real time; one WebSocket carries every tile, because
seven MJPEG streams would use up the browser's six HTTP/1.1 connections; and why demo mode
blocks URL sources (SSRF). The full write-up is in [System design](architecture/README.md).
