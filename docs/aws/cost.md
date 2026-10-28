# Cost

## Cost estimate

These are us-east-1 on-demand list prices as of late 2026. Check the
[AWS Pricing Calculator](https://calculator.aws/) before relying on them.

| Item | Always on | With nightly stop (15 h/day) |
|---|---:|---:|
| EC2 `g4dn.xlarge`: $0.526/h × 730 h | $384 | ~$240 |
| EBS gp3 100 GB: $0.08/GB-month (baseline 3,000 IOPS / 125 MB/s included) | $8 | $8 |
| Public IPv4 (Elastic IP): $0.005/h, also charged while stopped | $3.65 | $3.65 |
| Secrets Manager: 1 secret | $0.40 | $0.40 |
| AWS WAF: web ACL $5 + 3 rules × $1 + $0.60 per million requests | ~$8 | ~$8 |
| CloudWatch: ~40 custom metrics (4 per camera + 9 fleet) × $0.30, first 10 free; 6 alarms and 1 dashboard (within the free tier) | ~$9 | ~$9 |
| CloudWatch Logs: ingestion $0.50/GB (metric lines are ~10 KB/min; access logs vary) | ~$1 | ~$1 |
| SNS, Budgets (first two free), Lambda custom resource, Scheduler, S3 asset | < $1 | < $1 |
| CloudFront: see below | $0 within free tier | $0 within free tier |
| **Total** | **≈ $415/month** | **≈ $270/month** |

**CloudFront egress** is the cost that varies with usage. The live wall streams every
camera's 480 px frames over one WebSocket. Measured locally at about 4.5 FPS, those tiles
were **20–100 KB per frame** (92–443 KB/s per camera; the detailed plaza is the largest).
The enlarged view adds one full 960 px stream at 60–350 KB per frame
([architecture.md](../architecture/performance.md)). At the demo's 8 FPS cap:

- One person watching the seven-camera wall uses about **2 MB/s, roughly 7 GB per hour**.
- 20 visitors × 15 minutes a day on the wall comes to about 1 TB a month.

CloudFront's always-free tier covers the first **1 TB/month** of egress and 10 million
requests. After that, egress to North America and Europe costs about $0.085/GB (≈ $85 per
extra TB). Origin traffic from EC2 to CloudFront is free, and so is inbound traffic such as
phone publishing. To control egress: lower `ZW_STREAM_FPS` (bandwidth scales linearly with
it) or `ZW_JPEG_QUALITY`, and keep the nightly stop enabled.

Spot pricing for g4dn.xlarge is usually 60–70% cheaper, but a Spot interruption would take
the demo down. Moving to Spot is a small change if that's acceptable.

## Cost and abuse controls

On a public URL, the instance is a fixed cost. **CloudFront egress grows with every viewer
watching video**, so the controls focus on video. Counts, alerts and incidents travel over
the small status socket and are never limited.

| Control | Where | What it does |
|---|---|---|
| Pause hidden tabs | Browser (`frontend/src/lib/video.ts`) | Video stops the moment a tab goes to the background and resumes when it's visible |
| Idle pause | Browser, timeout from `/api/config` | After `videoIdleTimeoutS` (10 min) without input, video pauses until the next input |
| Session limit | Server (`ZW_VIDEO_SESSION_MAX_S`) | Video connections close after 30 min with code 4408. The page asks before resuming, so a tab left open on a wall screen stops costing bandwidth |
| Viewer cap | Server (`ZW_MAX_VIDEO_VIEWERS`) | Past 40 concurrent video connections, new ones get 4429 (WebSocket) or 503 (MJPEG). The page shows "at capacity" and retries after 30 s |
| Rate limit | WAF | 429 for any IP over 2,000 requests in 5 minutes. Video and status are a few long-lived connections, so normal use is far below this |
| Managed rules | WAF | AWS IP-reputation list (known bots, scanners) and known-bad inputs (exploit payloads) |
| Budget | AWS Budgets | Email/SNS alert at 80% of the monthly budget, or when the forecast passes 100% |
| Nightly stop | EventBridge Scheduler (optional) | Pay for the GPU only during demo hours |

Worst case with the defaults: 40 viewers × about 2 MB/s ≈ 80 MB/s ≈ 290 GB per hour, roughly
$25 per hour beyond the free tier. The `ViewersNearLimit` alarm and the budget exist so that
doesn't go unnoticed; lower `maxVideoViewers` or `ZW_STREAM_FPS` to cap it harder.

---

Part of the [AWS deployment](README.md) documentation.
