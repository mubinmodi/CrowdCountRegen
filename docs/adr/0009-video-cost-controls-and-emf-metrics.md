# 0009. Cap and pause video for cost; publish metrics as EMF log lines

**Status:** Accepted

## Context

On the public demo, the GPU instance is a fixed cost, but **video egress grows with every
viewer**: about 2 MB/s for one person watching the seven-camera wall, roughly $0.60 an hour
each beyond CloudFront's free tier. A tab left open on a wall screen, a crawler holding
connections, or a link shared widely can run that up unnoticed. Counts, alerts and incidents,
by contrast, are a few hundred bytes a second.

Operating it also needs numbers: is every camera running, is the GPU keeping up, how many
people are watching. The backend had none of these as metrics.

## Decision

**Spend bandwidth only on someone watching**, at each layer:

| Layer | Control |
|---|---|
| Browser | Video stops while the tab is hidden and after 10 minutes without input (`video_idle_timeout_s` from `/api/config`); any input resumes it |
| Server | Video connections close after 30 minutes (`4408`), and the page asks before resuming. Past `ZW_MAX_VIDEO_VIEWERS`, new video connections get `4429`/`503`, and the page retries after 30 s |
| Edge | AWS WAF per-IP rate limit, plus AWS's IP-reputation and known-bad-input rules |
| Account | AWS Budget alerts at 80% actual and 100% forecast |

Only video is limited. The status socket keeps counts, alerts and the incident log live for
everyone, so a capped visitor still sees a working product. WebSocket refusals accept the
connection and then close it with a code, because a refusal during the handshake reaches the
browser as a generic `1006`, and "busy" would be indistinguishable from "down".

**Metrics are CloudWatch Embedded Metric Format JSON lines on stdout**, one per camera and one
for the fleet each minute. Docker's awslogs driver already ships stdout to CloudWatch Logs,
which extracts EMF into metrics. Mean detector *lock wait* is published next to inference
time as the saturation signal.

## Consequences

- Egress is bounded: at most `max_video_viewers` × 2 MB/s, and alarmed at 80% of it.
- No metrics SDK, agent, credentials or extra network calls in the app. Metrics cost what
  they cost in CloudWatch (~40 custom metrics, about $9/month). The same lines are readable
  locally and portable to any log-based pipeline.
- Per-camera metrics use a `CameraId` dimension, so dashboards use `SEARCH` expressions to
  show whatever cameras exist rather than a fixed list.
- A determined client can ignore the idle pause; the server-side session limit and viewer
  cap are what actually bound the cost.
