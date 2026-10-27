# 0006. Public demo mode: shared account, push-only sources

**Status:** Accepted

## Context

The demo must open straight onto a working console, with no sign-up, on a public URL.
Removing login on its own would be dangerous, because the app's core feature, "connect to
this camera", makes the **server** open a URL, file or device a user chooses:

| Abuse | Through |
|---|---|
| Read cloud credentials from the instance metadata service | A camera or snapshot URL `http://169.254.169.254/…`, or Test connection |
| Probe or reach internal services | Stream/snapshot URLs, ONVIF lookups to arbitrary addresses |
| Read server files | A `file` source such as `/etc/…` |
| Burn GPU time | Adding many cameras |

## Decision

`CC_DEMO_MODE=true` turns on:

- **No login.** Every request acts as one shared demo user, and the sign-in pages redirect to
  the app.
- **Push-only sources.** Visitors can add *browser* cameras (a phone or laptop sends frames
  to the server), but creating, re-sourcing or probing any other kind returns 403, as do both
  ONVIF endpoints. Browser cameras are capped (`CC_DEMO_MAX_BROWSER_CAMERAS`, default 4).
- **Protected scenarios.** Seeded scenario cameras can have their name, zone, mode and limit
  edited, but can't be deleted or given a new source. `POST /api/demo/reset` restores them,
  and visitors can click Reset at any time.
- On AWS, defence in depth: IMDSv2 with a hop limit of 1 (containers can't reach instance
  credentials), and a security group that only admits CloudFront.

## Consequences

- The demo is safe to share publicly without a WAF, and the server never connects anywhere a
  visitor typed.
- Visitors share state: one person's zone edit is everyone's. That's acceptable for a demo,
  and Reset undoes it.
- Real IP cameras can't be shown on the public demo. That's the point; run the app normally
  (not in demo mode) for that.
