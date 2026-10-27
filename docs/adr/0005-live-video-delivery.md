# 0005. MJPEG for one camera, a multiplexed WebSocket for the wall

**Status:** Accepted

## Context

The UI needs annotated live video with low delay, in any browser, without a media server.
WebRTC gives the lowest latency but needs signalling, STUN/TURN and an SFU to scale. HLS/DASH
adds seconds of delay and an encoder. **MJPEG** (a `multipart/x-mixed-replace` response) works
in every `<img>` tag with no client code and fits a pipeline that already produces a JPEG per
frame.

MJPEG has two problems on a multi-camera wall:

1. **Connection limits.** Over HTTP/1.1 a browser allows 6 connections per host, and MJPEG
   responses never end. A seven-camera wall used all of them, and every later request (API
   calls, navigation) hung. HTTP/2 (CloudFront) avoids this, but local development and plain
   nginx serve HTTP/1.1.
2. **Bandwidth.** A full 960 px stream is 60–350 KB per frame. Seven tiles at 8 FPS would be
   about 7 MB/s per viewer for images displayed at about 400 px.

## Decision

- Each worker encodes two JPEGs per frame: 960 px (full) and 480 px (small), an extra ~2 ms.
- The **wall** opens one WebSocket, `/api/ws/frames`, which sends every camera's newest small
  JPEG as a binary message: a 4-byte big-endian camera id followed by the image. The browser
  turns each into an object URL and sets it directly on that tile's `<img>`, bypassing React.
- The **enlarged view** uses the full MJPEG stream for its one camera.
- Both send only the newest frame, at `CC_STREAM_FPS`, so a slow client gets fewer frames,
  never a backlog.

## Consequences

- The wall uses one connection however many cameras it shows, and API calls stay fast (8
  concurrent in 93 ms with the wall open).
- Tiles use a quarter to a third of the bytes (measured 92–443 KB/s vs 266–1666 KB/s per
  camera), which matters most when CloudFront egress is the running cost.
- Video is still a JPEG sequence: no inter-frame compression, so several times larger than
  H.264 at the same quality. If bandwidth became the main cost, the next step is encoding the
  annotated output to H.264 and serving it over WebRTC or low-latency HLS.
