# Path to production

This stack is shaped for a cheap, always-reachable demo. For a real multi-tenant service:

1. **Split the API from the vision workers.** Run the FastAPI API as a stateless service
   (ECS Fargate behind an ALB). Move camera workers to a separate GPU worker tier that claims
   cameras from a queue or lease table and publishes frames and counts. Stream video through
   a media path (for example, WebRTC/HLS through a media server, or Kinesis Video Streams)
   instead of MJPEG through the API.
2. **Use RDS for PostgreSQL** (or Aurora) instead of SQLite. The backend already supports
   `ZW_DATABASE_URL=postgresql+psycopg://…`.
3. **Autoscale the GPU workers** on ECS with an EC2 GPU capacity provider (g4dn/g5/g6), scaled
   on cameras per GPU. Store images in ECR and build them in CI instead of on the instance.
4. **Send alerts through SNS and EventBridge**, publishing occupancy and incident events so
   email, SMS, webhooks and downstream automations can subscribe.
5. **Add Cognito** user pools for sign-up and sign-in (with MFA) instead of the demo user,
   keeping per-owner scoping in the API.
6. **Edge:** a custom domain with an ACM certificate (TLS 1.2+ minimum), CloudFront access
   logs, WAF logging, and the AWS managed common rule set tuned for the API. Consider a VPC
   origin, so the instances have no public IP at all.
7. **Operations:** VPC flow logs, traces (OpenTelemetry → X-Ray), backups
   (RDS snapshots), and secret rotation with a key-versioning scheme for stored camera
   passwords.

---

Part of the [AWS deployment](README.md) documentation.
