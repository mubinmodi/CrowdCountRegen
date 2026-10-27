# 0003. Alert limits live outside the frame pipeline

**Status:** Accepted

## Context

A camera's worker is rebuilt whenever its `CameraConfig` changes, because the source, zone
and drawing style affect processing. The alert threshold used to be part of that config, so
**changing a camera's limit restarted its worker**. The new worker started a fresh tracker and
zone counter, which reset the live unique-visitor count to zero. Worse, everyone already in
the zone got a new tracker id and was counted again as an entry in the stored analytics.

The worker never used the threshold; it was only compared against the count afterwards, in
three places in the frontend.

## Decision

- `CameraConfig` holds only what shapes processing: source, zone and mode (mode changes the
  drawing).
- The manager keeps each camera's **alert limit** separately (`alert_limit(mode, threshold)`)
  and applies a change immediately.
- `manager.status()` returns one frozen `CameraSnapshot`, including `alert_limit` and
  `over_limit`. Every API route and the incident monitor use it, and the frontend reads
  `over_limit` instead of recomputing it.

## Consequences

- Editing a limit is instant and keeps tracking state; a regression test fails on the old
  behaviour.
- There is one definition of "alerting", on the server, so the live wall, the camera list,
  the alert badges and the incident log can't disagree.
- Adding a new limit-like setting means deciding whether it shapes processing (config) or
  interprets results (manager). The docstring on `CameraConfig` states that rule.
