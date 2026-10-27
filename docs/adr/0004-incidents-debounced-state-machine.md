# 0004. Incidents come from a debounced state machine sampled at 2 Hz

**Status:** Accepted

## Context

A construction site needs a record of exclusion-zone breaches: when, how long, how many
people, and what it looked like. The per-frame alert flag is noisy. A one-frame false
detection would log a breach, and a person briefly hidden behind a machine would split one
breach into two. Occupancy alerts are noisier still, because counts hover around the limit.

## Decision

- A pure `IncidentTracker` per camera turns `(time, alerting, occupancy)` samples into
  *opened* and *closed* events. It opens after the alert has held for `open_after` (1 s) and
  closes after the camera has been clear for `close_after`: **3 s for danger zones, 15 s for
  occupancy**. Event times are when the condition began and cleared, not when the debounce
  ended. Peak occupancy includes the debounce window.
- One manager thread samples `status()` for every camera at 2 Hz, feeds the trackers, and
  writes rows. Each incident stores the annotated JPEG at the moment it opened. Only the
  newest 200 per camera are kept, and incidents left open across a restart are closed at
  their start time.

## Consequences

- The frame pipeline never touches the database for alerts, and every alert decision is in
  one place with no I/O, tested with a fake clock.
- There is up to ~0.5 s of sampling delay on top of the debounce, which is fine for logging.
  A real-time siren would subscribe to the worker directly.
- Notifications (SMS, email, webhooks, EventBridge) have a single place to hook in: the
  *opened* event.
- Looping demo footage opens an incident every loop. That's correct per loop, but it means
  retention matters, which is why the 200-per-camera cap exists.
