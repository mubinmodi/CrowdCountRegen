# 0007. AWS: one GPU instance behind CloudFront, immutable redeploys

**Status:** Accepted. Details in [deployment-aws.md](../deployment-aws.md).

## Context

The demo needs a GPU (for 1280 px inference on seven cameras), HTTPS (browsers only allow
phone-camera access on secure origins), WebSockets and long-lived MJPEG responses, low cost,
and an easy way to stop it between demos. The backend is stateful by design ([ADR 0001](0001-single-process-thread-per-camera.md)).

Options considered:

| Option | Why not |
|---|---|
| ECS on Fargate | No GPUs |
| ECS on EC2 GPU capacity / EKS | Adds a cluster, capacity provider and load balancer for a single task; same instance underneath |
| SageMaker endpoint | Request/response inference; doesn't fit a stateful per-camera pipeline that needs to stream |
| App Runner / Lightsail containers | No GPU; App Runner has no WebSockets |
| ALB + ACM certificate | Needs a domain for the certificate; about $16/month more than CloudFront's free default certificate |

## Decision

One `g4dn.xlarge` (T4) from the AWS Deep Learning Base AMI, running the two Compose services,
in a public subnet with an Elastic IP. **CloudFront** in front provides TLS on its default
domain, HTTP/2 to viewers, edge caching of hashed assets, and the only path in: the security
group admits port 80 from CloudFront's origin-facing prefix list only. The app source is
shipped as a CDK S3 asset and built on the instance; a code change **replaces** the instance,
which seeds itself on boot. Access is through SSM Session Manager, with no SSH.

## Consequences

- One instance to pay for and to stop; no NAT gateway, no load balancer, no registry.
- Redeploys take about 10–15 minutes (GPU image build and model warm-up), behind a CloudFormation
  health gate. Demo state resets on each deploy, which is fine because it reseeds itself.
- No high availability. A status-check alarm reboots it, or stop/starts it onto new hardware.
  Production would use the multi-node design in [architecture.md](../architecture.md#scaling-beyond-one-node).
- The account needs a G-instance vCPU quota of at least 4, and permission to use CloudFormation.
