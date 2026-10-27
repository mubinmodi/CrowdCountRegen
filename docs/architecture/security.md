# Security

- **Accounts.** Argon2id password hashes; signed, expiring session tokens in httpOnly
  SameSite=Lax cookies (Secure behind HTTPS); constant-time login for unknown emails.
- **Tenant isolation.** Every query is scoped to the owner; other users' ids return 404.
- **Camera credentials** are kept out of URLs, encrypted at rest (Fernet, key derived from
  `CC_SECRET_KEY`), never returned to the browser, and only put back into the URL at the moment
  FFmpeg connects.
- **Server-side request forgery is the main risk.** Any camera source is opened *by the
  server*, so in a multi-user or public deployment a user could point one at
  `http://169.254.169.254/` (cloud metadata), an internal service or a local file. That's
  acceptable for a self-hosted tool where every user is trusted, but not on a public URL.
  **Demo mode** therefore only allows push sources: visitors can add phone cameras, which send
  frames *to* the server, while stream/snapshot/file/webcam sources, **Test connection** on
  them, and ONVIF discovery all return 403. Scenario cameras can be edited and reset but not
  deleted or given a new source, and phone cameras are capped (default 4).
  [ADR 0006](../adr/0006-public-demo-mode.md) covers the threat model.
- **Publish tokens** act like RTMP stream keys: 192-bit random, rotatable, and only valid for
  browser cameras.
- **Abuse and cost.** Video, the one cost that grows per viewer, pauses in hidden or idle
  tabs, expires after 30 minutes, and is capped at a number of concurrent viewers. AWS WAF
  rate-limits each IP and applies AWS's reputation and known-bad-input rules
  ([ADR 0009](../adr/0009-video-cost-controls-and-emf-metrics.md)).
- **AWS.** No SSH, IMDSv2 only, the security group only admits CloudFront, the secret lives
  in Secrets Manager, and deploys use short-lived OIDC roles behind a manual approval
  ([ADR 0010](../adr/0010-deploy-with-github-oidc-and-approval.md),
  [security model](../aws/security.md#security-model)).

---

Part of the [system design](README.md) documentation.
