# Documentation

Start with the [project README](../README.md) for the overview. Everything else is here, one
topic per page.

## Guides

| Page | For |
|---|---|
| [Getting started](getting-started.md) | Running it locally or with Docker, your first camera, using a phone, troubleshooting |
| [User guide](user-guide.md) | Every screen: live wall, cameras and zones, phone cameras, incidents, analytics |
| [Camera sources](camera-sources.md) | Each source type, finding a camera's URL, credentials, reconnects, ONVIF |
| [The demo](demo.md) | The seven scenarios, running them, and a five-minute walkthrough |

## Reference

| Page | For |
|---|---|
| [Configuration](configuration.md) | Every `CC_*` setting, with defaults and presets |
| [API](api.md) | Every endpoint, the WebSocket protocols and close codes |
| [Development](development.md) | Code layout, checks, tests, migrations, extension points |

## System design

How it works and why, in [`architecture/`](architecture/README.md):

| Page | Covers |
|---|---|
| [Overview](architecture/README.md) | Requirements, the big picture, modules, known limitations |
| [The frame pipeline](architecture/frame-pipeline.md) | From camera to browser, and the threading model |
| [Zones, tracking and counting](architecture/counting.md) | Foot position in normalized polygons, unique entries |
| [Alerts and incidents](architecture/alerts-and-incidents.md) | The alert rule and the debounced incident state machine |
| [Live video delivery](architecture/live-video.md) | Status socket, multiplexed tile video, MJPEG, pausing and capping |
| [Data model and storage](architecture/data-model.md) | Tables, per-minute aggregation, analytics |
| [Performance and capacity](architecture/performance.md) | Measurements, the capacity model, tuning |
| [Failure modes](architecture/reliability.md) | What breaks and how it recovers |
| [Security](architecture/security.md) | Accounts, isolation, credentials, SSRF, demo mode |
| [Observability](architecture/observability.md) | Stream health, metrics, logs, alarms |
| [Scaling beyond one node](architecture/scaling.md) | The multi-node design |

The decisions behind the design are recorded one by one in [`adr/`](adr/README.md).

## AWS deployment

The public demo on AWS, in [`aws/`](aws/README.md):

| Page | Covers |
|---|---|
| [Overview](aws/README.md) | Architecture, request path, every resource and why |
| [Deploying and operating](aws/deploy.md) | Prerequisites, deploy, the boot sequence, operating, updating, teardown |
| [Cost](aws/cost.md) | Monthly estimate and the cost and abuse controls |
| [Monitoring and alerts](aws/monitoring.md) | Metrics, alarms, dashboard |
| [Continuous deployment](aws/ci-cd.md) | GitHub Actions with OIDC roles and a manual approval |
| [Security model](aws/security.md) | How the deployment is locked down; cdk-nag |
| [Path to production](aws/production.md) | What changes beyond a single-instance demo |

## History

[The original project](original-project.md): the 2021 undergraduate project this rewrites,
and what changed.
