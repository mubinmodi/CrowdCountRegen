# Architecture decision records

Short records of decisions that shape the system: the context, what was decided, and what it
costs. Newer records can supersede older ones; nothing is edited after it's accepted, except
its status.

| # | Decision | Status |
|---|---|---|
| [0001](0001-single-process-thread-per-camera.md) | One process, a thread per camera, one shared detector behind a lock | Accepted |
| [0002](0002-count-by-feet-in-normalized-polygons.md) | Count by foot position in normalized polygons; unique entries from tracker ids | Accepted |
| [0003](0003-alert-limits-outside-the-pipeline.md) | Alert limits live outside the frame pipeline | Accepted |
| [0004](0004-incidents-debounced-state-machine.md) | Incidents come from a debounced state machine sampled at 2 Hz | Accepted |
| [0005](0005-live-video-delivery.md) | MJPEG for one camera, a multiplexed WebSocket for the wall | Accepted |
| [0006](0006-public-demo-mode.md) | Public demo mode: shared account, push-only sources | Accepted |
| [0007](0007-aws-single-gpu-instance-behind-cloudfront.md) | AWS: one GPU instance behind CloudFront, immutable redeploys | Accepted |
| [0008](0008-demo-footage-fetched-at-boot.md) | Demo footage is downloaded and trimmed at first boot, not committed | Accepted |
