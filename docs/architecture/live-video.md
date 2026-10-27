# Live video delivery

| Channel | Carries | Rate | Used by |
|---|---|---|---|
| `GET /api/ws/live` (WebSocket) | Every camera's status: state, counts, FPS, alert, errors | 2 Hz | Every page |
| `GET /api/ws/frames` (WebSocket, binary) | Every camera's newest 480 px JPEG, each prefixed with a 4-byte camera id | `CC_STREAM_FPS` | Live wall tiles |
| `GET /api/cameras/{id}/stream.mjpg` | One camera's 960 px MJPEG | `CC_STREAM_FPS` | Enlarged view, embeds |

The wall used to be one MJPEG `<img>` per tile. Over HTTP/1.1 (Vite's dev proxy, plain
nginx) a browser allows **6 connections per host**, and MJPEG responses never end, so a
seven-camera wall used them all and every later request (API calls, page loads) hung.
Multiplexing all tiles over one WebSocket removes the limit and is also cheaper: tiles get
480 px frames, a quarter to a third of the bytes of the full stream ([measured](performance.md)). Frames
are handed to `<img>` elements directly through object URLs, not React state, so a wall at
8 FPS doesn't re-render the page 50 times a second ([ADR 0005](../adr/0005-live-video-delivery.md)).

## Why not WebRTC or HLS

WebRTC gives the lowest latency, but needs signalling, STUN/TURN and an SFU to serve more
than a few viewers. HLS and DASH add seconds of delay and an encoder. The pipeline already
produces one annotated JPEG per frame, and a JPEG sequence needs no client code (MJPEG plays
in any `<img>`) and no media server. The cost is size: there's no inter-frame compression,
so it's several times larger than H.264 at the same quality. That's acceptable at demo scale,
and the next step is in [ADR 0005](../adr/0005-live-video-delivery.md).

## Every handoff keeps only the newest frame

Both video channels send the latest JPEG at `CC_STREAM_FPS`, never a queue. A slow viewer
gets fewer frames, not a growing buffer, and can't slow down the camera's pipeline, because
sending only reads the worker's latest JPEG under its lock.

## Pausing and capping video

Video is the only part of the system whose cost grows with every viewer, so it only flows
while someone is watching ([ADR 0009](../adr/0009-video-cost-controls-and-emf-metrics.md)).
Counts, alerts and incidents arrive over the status socket and are never paused or capped.

| Why video stops | Decided by | Resumes |
|---|---|---|
| The tab is hidden | Browser (`frontend/src/lib/video.ts`) | When it's visible again |
| No input for `CC_VIDEO_IDLE_TIMEOUT_S` (published in `/api/config`) | Browser | On the next input |
| Session older than `CC_VIDEO_SESSION_MAX_S` | Server: closes the frames socket with **4408** and ends MJPEG | When the viewer clicks *Resume* |
| More than `CC_MAX_VIDEO_VIEWERS` open video connections | Server: closes with **4429**, or answers MJPEG with **503** + `Retry-After: 30` | By itself after 30 s, or *Retry now* |

The browser side is a small state machine, the *video gate*, with one state per row above
(and unit tests in `video.test.ts`). The frames socket opens only while the gate is open, and
the server's close codes move the gate into the matching state instead of triggering an
immediate reconnect. The server accepts a socket before refusing it, because a socket closed
during the handshake reaches the browser as a generic code 1006, and "busy" would look the
same as "down".

The full protocol of each channel (message formats, close codes) is in the
[API reference](../api.md#websockets).

---

Part of the [system design](README.md) documentation.
