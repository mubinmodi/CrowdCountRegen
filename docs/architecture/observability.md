# Observability

- **In the product:** per-camera stream health in the UI (state, error code and hint,
  resolution, codec, achieved FPS, reconnect count), and the incident log.
- **Metrics:** with `ZW_METRICS=emf`, the backend writes CloudWatch Embedded Metric Format
  lines to stdout every minute. Per camera: FPS, occupancy, alerting and reconnects. For the
  fleet: running/stalled/alerting cameras, open incidents, video viewers, inferences per
  minute, mean inference time and mean **lock wait** (time queued for the shared detector).
  Lock wait is the saturation signal: once it exceeds the inference time, cameras are
  queuing for the GPU. Publishing through logs means no SDK, agent or credentials in the
  container ([ADR 0009](../adr/0009-video-cost-controls-and-emf-metrics.md)).
- **Logs and alarms on AWS:** both containers log to CloudWatch through Docker's awslogs
  driver. Alarms fire on stalled cameras, a silent backend, a saturated detector and viewers
  near the cap, alongside the EC2 status checks, all to one SNS topic; a dashboard puts them
  next to CloudFront egress ([details](../aws/monitoring.md)).
- **Health:** `GET /api/health`, which the AWS boot health gate uses before traffic moves to
  a new instance.

Still missing for production: traces (OpenTelemetry → X-Ray) to show where a slow frame
spends its time, and per-request latency metrics for the API.

---

Part of the [system design](README.md) documentation.
