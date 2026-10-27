# Monitoring and alerts

The backend publishes metrics as **CloudWatch Embedded Metric Format** JSON lines on stdout
every minute (`CC_METRICS=emf`, `backend/app/metrics.py`). The awslogs driver carries them
into CloudWatch Logs, where CloudWatch extracts them into the `CrowdCounting` namespace. No
SDK calls, no agent, no credentials in the container.

| Metric | Dimension | Meaning |
|---|---|---|
| `FPS`, `Occupancy`, `Alerting`, `Reconnects` | `CameraId` | Per camera: achieved processing rate, people in the zone, whether it's over its limit, and reconnects in the last minute |
| `Cameras`, `CamerasRunning`, `CamerasStalled`, `CamerasAlerting` | (none) | Fleet state. *Stalled* means in `error` or `connecting` |
| `InferenceMs`, `LockWaitMs`, `Inferences` | (none) | Mean model time, mean time cameras queued for the shared model, and inferences per minute |
| `VideoViewers`, `IncidentsOpen` | (none) | Open video connections, open incidents |

| Alarm | Fires when | Usually means |
|---|---|---|
| `CamerasStalled` | Any camera in error/connecting for 5 min | A source is down. Check its stream health page |
| `BackendDown` | No running camera, or no metrics, for 10 min | The backend container or instance is down. Silence is ignored when the nightly schedule is on |
| `DetectorSaturated` | Cameras wait more than 2× the inference time for the model, for 15 min | The GPU is the bottleneck: lower `CC_MAX_FPS` or `CC_DETECTOR_IMGSZ` |
| `ViewersNearLimit` | Video viewers ≥ 80% of the cap | A traffic spike, and visitors are about to get "busy" |
| Instance / system status checks | EC2 health checks fail | Rebooted or restarted automatically (see [Resources](README.md#resources-and-why-each-one-exists)) |

All of them notify the `Alerts` topic when they fire and when they recover. The dashboard
puts these metrics next to CloudFront's request, error-rate and egress graphs and a
Logs Insights panel of recent errors.

---

Part of the [AWS deployment](README.md) documentation.
