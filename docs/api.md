# API reference

The backend is a FastAPI app. Everything lives under `/api`, and the frontend uses exactly
this API. The interactive OpenAPI docs are at **`/docs`** on a running backend (schema at
`/openapi.json`). This page adds what OpenAPI doesn't describe well: the WebSocket protocols,
close codes and the rules around ownership and demo mode.

## Conventions

- **Auth** is a signed, expiring session token in the httpOnly cookie `zw_session` (set by
  sign-up and login, `SameSite=Lax`, `Secure` when `ZW_COOKIE_SECURE=true`). Browsers send it
  automatically, including on WebSockets and `<img>` requests, which is why the frontend and
  API share an origin (Vite's proxy in development, nginx in Docker).
- **Demo mode** (`ZW_DEMO_MODE=true`): every request acts as the shared demo user, with no
  cookie needed.
- **Ownership:** every camera-scoped route checks that the camera belongs to the caller and
  answers **404** (not 403) otherwise, so other users' ids can't be discovered.
- **Times** are UTC, ISO 8601.
- **Errors** are `{"detail": "message"}`, or FastAPI's list of field errors for 422.

| Status | When |
|---|---|
| 401 | Not signed in |
| 403 | Refused in demo mode (a non-browser source, a probe of one, ONVIF, deleting or re-sourcing a scenario) |
| 404 | Not found, or not yours |
| 409 | Email already registered; a publish token for a non-browser camera; demo phone-camera cap reached |
| 422 | Validation (e.g. a zone with fewer than 3 points, a stream URL without a host) |
| 503 | MJPEG requested while video viewers are at `ZW_MAX_VIDEO_VIEWERS` (`Retry-After: 30`); no frame yet for a snapshot |

## Meta

| Endpoint | Returns |
|---|---|
| `GET /api/health` | `{"status": "ok", "detector": "ultralytics"}`. Used by health checks |
| `GET /api/config` | `{"demo_mode": bool, "detector": str, "video_idle_timeout_s": number \| null}`. Read by the frontend before anything else |

## Accounts

| Endpoint | Body | Notes |
|---|---|---|
| `POST /api/auth/signup` | `{email, name, password}` (password 8–128 chars) | 201 + session cookie |
| `POST /api/auth/login` | `{email, password}` | Session cookie. Unknown emails take as long as wrong passwords |
| `POST /api/auth/logout` | | 204, clears the cookie |
| `GET /api/auth/me` | | `{id, email, name}` |

## Cameras

| Endpoint | Notes |
|---|---|
| `GET /api/cameras` | Your cameras, oldest first |
| `POST /api/cameras` | Create. Starts its worker |
| `GET /api/cameras/{id}` | One camera |
| `PATCH /api/cameras/{id}` | Omitted fields are unchanged. Changing source, zone or mode restarts the worker; name, description and limit apply without a restart |
| `DELETE /api/cameras/{id}` | Deletes the camera with its counts and incidents |
| `POST /api/cameras/probe` | Connect once, without saving |
| `POST /api/cameras/{id}/publish-token` | Browser cameras: issue a new publish link; the old one stops working |
| `GET /api/cameras/{id}/status` | The live status (the same object the status socket sends) |
| `GET /api/cameras/{id}/snapshot.jpg` | The latest raw frame, without annotations (used by the zone editor) |
| `GET /api/cameras/{id}/stream.mjpg[?size=small]` | Live annotated MJPEG. See [Video](#mjpeg-stream) |

**Camera fields** (create and patch):

| Field | Type | |
|---|---|---|
| `name` | string, 1–200 | Required on create |
| `kind` | `stream` · `snapshot` · `browser` · `webcam` · `file` | Inferred from `source` when omitted |
| `source` | string | URL, device index (`0`) or server path. Credentials in a URL are moved to `username`/`password` |
| `username`, `password` | string or null | Stored encrypted, never returned. Omit `password` to keep the stored one; `null` clears it |
| `options` | object | `rtsp_transport` (`tcp`·`udp`·`auto`), `snapshot_interval_ms` (100–60000), `insecure_tls`, `width` (webcam) |
| `zone` | `[[x, y], …]` or null | At least 3 points, normalized to 0–1. `null` = the whole frame |
| `mode` | `occupancy` · `danger_zone` | Default `occupancy` |
| `threshold` | integer ≥ 0 or null | Most people allowed in the zone. Occupancy: `null` = no alert. Danger zone: `null` = 0 |
| `description` | string or null | Shown in the enlarged view |

Responses add `id`, `has_password`, `scenario` (demo scenario key, or null),
`publish_token` (browser cameras) and `created_at`.

**Probe** takes the same source fields, plus an optional `camera_id` to reuse that camera's
stored password. It returns `{ok, error_code, message, hint, stream: {width, height, fps,
codec, live}, first_frame_ms, preview}`, where `preview` is a `data:image/jpeg;base64,…` URL.
Error codes: `auth`, `forbidden`, `not_found`, `unreachable`, `timeout`, `unsupported`,
`invalid`, `no_video`, `ended`, `waiting` (a browser camera nobody is publishing to), and
`error`.

**Status** (`/status` and each entry of the status socket):

| Field | |
|---|---|
| `camera_id` | |
| `state` | `starting` · `connecting` · `running` · `waiting` · `error` · `stopped` |
| `error`, `error_code`, `hint` | The last failure, a code from the list above, and what to try |
| `occupancy` | People in the zone in the latest processed frame |
| `unique_entries` | Distinct tracked people who entered the zone since the worker started |
| `fps` | Achieved processing rate |
| `stream` | `{width, height, fps, codec, live}` of the source, once known |
| `reconnects` | Since the worker started |
| `publisher_connected` | Browser cameras: whether a device is publishing |
| `alert_limit` | Most people allowed (from mode and threshold); null = never alerts |
| `over_limit` | Running and `occupancy > alert_limit`: the one definition of "alerting" |

## Incidents

| Endpoint | Notes |
|---|---|
| `GET /api/incidents[?camera_id=&limit=]` | Newest first, up to `limit` (1–500, default 100). Each: `{id, camera_id, started_at, ended_at, peak, limit, has_snapshot}`. `ended_at` is null while the incident is open |
| `GET /api/incidents/{id}/snapshot.jpg` | The annotated frame when the incident opened. Cacheable for a day |

How incidents open and close is described in
[Alerts and incidents](architecture/alerts-and-incidents.md).

## Analytics

`GET /api/analytics?hours=24[&camera_id=][&bucket_minutes=]`

- `hours`: 1 to 2160 (90 days). `bucket_minutes`: 1 to 1440; when omitted it's chosen from
  the range (1 min up to 2 h, 5 min up to 12 h, 15 min up to 2 days, 1 h up to 8 days, then
  6 h).
- Without `camera_id`, cameras are summed per minute before bucketing, so the result is the
  total across cameras. The combined peak is therefore an upper bound.

Returns `{camera_id, range_start, range_end, bucket_minutes, buckets: [{start,
avg_occupancy, peak_occupancy, entries}], summary: {peak_occupancy, peak_at, avg_occupancy,
total_entries}}`. Buckets are aligned to fixed boundaries, so they're stable between refreshes.

## ONVIF

| Endpoint | Body | Returns |
|---|---|---|
| `POST /api/onvif/discover` | | Devices answering a WS-Discovery multicast probe on the server's LAN: `[{xaddr, host, name, hardware}]` |
| `POST /api/onvif/streams` | `{xaddr, username, password}` | `{manufacturer, model, profiles: [{token, name, encoding, width, height, uri}]}`. Stream URIs come without credentials |

Both are refused (403) in demo mode, because they make the server contact addresses on its
network.

## Demo

`POST /api/demo/reset` restores every scenario camera's name, description, mode, zone and
limit, and returns them. Phone cameras visitors added are kept.

## Video

### MJPEG stream

`GET /api/cameras/{id}/stream.mjpg` is a `multipart/x-mixed-replace; boundary=frame`
response that works directly in an `<img>`. Each part is one annotated JPEG, 960 px wide, or
480 px with `?size=small`. Frames are sent at `ZW_STREAM_FPS`, and only when a new one exists.
When the server is at `ZW_MAX_VIDEO_VIEWERS`, it answers **503** with `Retry-After: 30`. With
`ZW_VIDEO_SESSION_MAX_S` set, the response ends after that long.

## WebSockets

All three authenticate with the session cookie (or demo mode) when they connect, except
publishing, which uses its token.

### `/api/ws/live`: status

Every 0.5 s the server sends `{"ts": <epoch seconds>, "cameras": [<status>, …]}` for all of
your cameras (the list is refreshed every 5 s). Nothing is sent by the client. Unauthenticated
connections are closed with **4401**. This socket is never paused or capped: counts, alerts
and the incident badge depend on it.

### `/api/ws/frames[?size=small|full]`: tile video

Binary messages, one per new frame per camera:

```
 0               4                                     n
 +---------------+-------------------------------------+
 | camera id     | JPEG bytes (starts with FF D8)      |
 | uint32, big-  |                                     |
 | endian        |                                     |
 +---------------+-------------------------------------+
```

`size` defaults to `small` (480 px). Only the newest frame of each camera is sent, at
`ZW_STREAM_FPS`, so a slow client gets fewer frames rather than a backlog. The server accepts
the connection before refusing it, so the browser receives the code:

| Close code | Meaning | What the frontend does |
|---|---|---|
| 4401 | Not authenticated | Stops |
| 4429 | At `ZW_MAX_VIDEO_VIEWERS` | Shows "at capacity", retries after 30 s |
| 4408 | Session reached `ZW_VIDEO_SESSION_MAX_S` | Shows *Resume video*, waits for a click |

### `/api/publish/{token}`: phone and laptop cameras

Used by the publish page (`/publish/<token>`) that the publish link and QR code open.

1. The client connects. An unknown or rotated token is closed with **4404**.
2. The server sends `{"type": "hello", "camera": "<name>"}`.
3. The client sends each frame as a **binary JPEG message** (at most 2 MB). The publish page
   sends 640, 960 or 1280 px frames at 5, 10 or 15 FPS.
4. About once a second the server sends `{"type": "status", …}` with the camera's status
   fields, so the phone can show the live count.
5. If another device starts publishing to the same camera, this one is closed with **4409**.
   There is one publisher per camera, and the newest one wins.

The token works like a stream key: whoever has it can publish to that camera until it is
rotated (`POST /api/cameras/{id}/publish-token`).
