# Deploying and operating

## Prerequisites

- **GPU quota.** The account needs a vCPU quota of at least **4** for **"Running On-Demand G
  and VT instances"** (Service Quotas, EC2, quota code **`L-DB2E81BA`**) in us-east-1. New
  accounts often have 0. Request the increase before deploying (it can take a day):

  ```bash
  aws service-quotas request-service-quota-increase --region us-east-1 \
    --service-code ec2 --quota-code L-DB2E81BA --desired-value 4 --profile <p>
  ```

- **Permissions.** The deploying identity, and any organization SCPs or permission
  boundaries above it, must allow these in us-east-1, plus the global services CloudFront
  and IAM:
  - **CloudFormation**: create, update and delete stacks and change sets.
  - **EC2/VPC**: VPC, subnets, route tables, internet gateway, security groups and rules,
    `RunInstances`/`TerminateInstances`, `Describe*` including images and managed prefix
    lists, Elastic IPs, and stop/start.
  - **SSM**: `GetParameters` (for the AMI parameter), and Session Manager for access.
  - **S3**: the CDK assets bucket.
  - **Secrets Manager**: create, read and delete a secret.
  - **CloudFront**: create, update and delete a distribution.
  - **IAM**: create roles, policies and instance profiles, and `iam:PassRole`.
  - **EventBridge and EventBridge Scheduler**: rules and schedules.
  - **CloudWatch**: alarms and dashboards. **CloudWatch Logs**: log groups.
  - **SNS**: topics and subscriptions. **AWS Budgets**: budgets.
  - **AWS WAF (wafv2)**: web ACLs in the CloudFront scope (us-east-1).
  - **Lambda**: the custom-resource provider function.
  - **STS**: assuming the CDK bootstrap roles.

  An SCP that denies CloudFormation, or EC2 VPC, security-group or image calls, blocks this
  deployment no matter what IAM permissions the user has.
- **Cost allocation tag.** For the budget to see this stack's costs, activate `Project` as a
  user-defined cost allocation tag (Billing console → Cost allocation tags) after the first
  deploy has tagged resources. Until then the budget reports no spend.
- **CDK bootstrap**, once per account and region (`npx aws-cdk@2 bootstrap`, below). It
  creates the `CDKToolkit` stack: the assets bucket and the deploy roles.
- **Local tools:** [uv](https://docs.astral.sh/uv/), Node.js 22+ (for `npx aws-cdk@2`),
  AWS CLI v2, and the [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
  for shell access. Docker isn't needed locally: images are built on the instance.

## Deploy

```bash
cd infra
uv sync
npx aws-cdk@2 synth --quiet                   # offline; runs the cdk-nag AwsSolutions checks
npx aws-cdk@2 bootstrap --profile <p>         # once per account/region
npx aws-cdk@2 deploy CrowdCounting --profile <p> -c crowdcounting:alertEmail=you@example.com
```

The app has two stacks: `CrowdCounting` (the demo) and `CrowdCountingGithubDeploy` (roles
for [Continuous deployment](ci-cd.md)). Name the one you mean.

The first deploy takes about 20–30 minutes. Most of that is the instance building the
backend image, which pulls about 3 GB of CUDA wheels. CloudFront deploys in parallel. When it
finishes, the stack prints these outputs:

| Output | |
|---|---|
| `Url` | `https://<id>.cloudfront.net`, the demo |
| `InstanceId` | |
| `SsmSessionCommand` | `aws ssm start-session --target i-… --region us-east-1` |
| `SecretArn` | Where `CC_SECRET_KEY` lives |
| `AlertsTopicArn` | The SNS topic alarms and the budget publish to |
| `DashboardUrl` | The CloudWatch dashboard |

The live wall fills in over the first minute or two after boot, as the demo seeder downloads
and trims each scenario video.

### Options (CDK context)

Pass these with `-c key=value`, or set them in `infra/cdk.json`:

| Key | Default | |
|---|---|---|
| `crowdcounting:schedule` | `false` | `true` adds the nightly stop / morning start schedules |
| `crowdcounting:stopCron` / `startCron` | `cron(0 23 * * ? *)` / `cron(0 8 * * ? *)` | EventBridge Scheduler expressions |
| `crowdcounting:timezone` | `America/New_York` | Time zone for those expressions |
| `crowdcounting:availabilityZones` | (first 2 in the account) | e.g. `us-east-1b,us-east-1c`. The instance goes in the first one. Use this if launch fails with *"…g4dn.xlarge is not supported in your requested Availability Zone"* or *InsufficientInstanceCapacity*. |
| `crowdcounting:amiId` | (latest DLAMI) | Pin an AMI id so a new DLAMI release doesn't replace the instance |
| `crowdcounting:maxVideoViewers` | `40` | Concurrent video connections before visitors get "busy" (counts keep working) |
| `crowdcounting:videoSessionMaxS` | `1800` | Video connections close after this long; the viewer clicks to resume |
| `crowdcounting:videoIdleTimeoutS` | `600` | Browsers pause video after this long without input |
| `crowdcounting:wafRateLimit` | `2000` | Requests per IP per 5 minutes before WAF answers 429 |
| `crowdcounting:monthlyBudgetUsd` | `450` | The monthly budget's limit |
| `crowdcounting:alertEmail` | (none) | Email subscribed to the alerts topic |
| `crowdcounting:githubRepository` | `mubinmodi/CrowdCountRegen` | Repository whose workflows may assume the deploy roles |
| `crowdcounting:githubOidcProviderArn` | (create one) | Reuse an existing GitHub OIDC provider (an account can only have one per URL) |

### Operating it

```bash
aws ssm start-session --target <InstanceId> --region us-east-1 --profile <p>
sudo tail -f /var/log/cloud-init-output.log                      # first-boot log
cd /opt/crowdcounting
sudo docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.aws.yml ps
sudo docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.aws.yml logs -f backend
nvidia-smi                                                       # GPU in use?
```

Logs are also in CloudWatch, without a shell:
`aws logs tail /crowdcounting/demo --follow --profile <p>`.

If the first boot fails, CloudFormation rolls back and deletes the instance. To keep a failed
instance around for debugging, deploy with `--no-rollback`.

## Boot sequence (user data)

`infra/crowdcounting_infra/bootstrap.sh` runs once, on the instance's first boot:

1. It installs `aws-cfn-bootstrap` and `unzip` if they're missing. It also installs the Docker
   **buildx** plugin (if missing or older than 0.17) and the **compose** plugin (if missing).
   Compose v2 builds through buildx, and the Dockerfiles use BuildKit cache mounts.
2. It registers the NVIDIA runtime with Docker (`nvidia-ctk runtime configure`) and checks the
   driver. The backend's PyTorch wheels need driver ≥ 580 (see
   [GPU notes](#gpu-notes-cuda-in-backenduvlock)). If there's no GPU or the driver is too
   old, it writes `CC_DEVICE=cpu` and logs a warning, so the demo still comes up.
3. It downloads and unzips the app to `/opt/crowdcounting`, reads the secret, and writes
   `/opt/crowdcounting/.env` (mode 600):
   `CC_SECRET_KEY`, `CC_DEMO_MODE=true`, `CC_STREAM_FPS=8`, `CC_DEMO_VIDEO_DIR=/data/demo-videos`,
   `CC_DEVICE=cuda:0`, `CC_DETECTOR=ultralytics`, `CC_DETECTOR_IMGSZ=1280`,
   `CC_CONFIDENCE=0.3`, `CC_COOKIE_SECURE=true`, the video cost controls
   (`CC_MAX_VIDEO_VIEWERS`, `CC_VIDEO_SESSION_MAX_S`, `CC_VIDEO_IDLE_TIMEOUT_S`, from CDK
   context), `CC_METRICS=emf`, and `AWS_REGION` / `CC_LOG_GROUP` for the logging override.
4. It runs `docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.aws.yml up -d --build`.
5. It waits up to 15 minutes for `http://localhost/api/health` (through nginx) and then reports
   success or failure to CloudFormation with `cfn-signal`. CloudFormation waits up to
   45 minutes for that signal.

`docker-compose.aws.yml` switches both containers to the `awslogs` log driver in non-blocking
mode, so a slow CloudWatch never stalls the app. `docker-compose.gpu.yml` gives the backend the GPU (`deploy.resources.reservations.devices`),
passes the whole `.env` to the backend container (`env_file`, so new `CC_*` settings need no
change to `docker-compose.yml`), and publishes `web` on host port 80 instead of 8080. Both
containers use `restart: unless-stopped`, so they come back after a reboot or a scheduled
stop/start.

## Updating

Merging to `main` deploys through [Continuous deployment](ci-cd.md). By hand:
make your changes, then run `npx aws-cdk@2 deploy CrowdCounting --profile <p>` again. Any change
to the included files changes the asset hash. The asset hash is part of the user data, so the
deploy replaces the instance (immutable deploys):

1. CloudFormation launches a new instance, which builds and starts the app.
2. Once the new instance's health check passes, the Elastic IP moves to it. CloudFront is not
   touched, because its origin name stays the same.
3. The old instance is terminated.

Expect a few seconds of dropped streams at the switch. **Demo data does not carry over**: the
database lives on the instance and is reseeded on boot, which is the intent for a demo. A
newer DLAMI behind the SSM parameter also triggers a replacement on the next deploy, unless
you pin `crowdcounting:amiId`.

Use `npx aws-cdk@2 diff CrowdCounting` to preview changes first. The deploy uploads your **working tree**
(uncommitted changes included), not a git commit.

## Tearing down

```bash
cd infra && npx aws-cdk@2 destroy CrowdCounting --profile <p>
npx aws-cdk@2 destroy CrowdCountingGithubDeploy --profile <p>   # if you set up deployment
```

This removes everything in the stack. The secret goes into Secrets Manager's default 30-day
recovery window. To delete it right away, run
`aws secretsmanager delete-secret --secret-id <SecretArn> --force-delete-without-recovery`.
The `CDKToolkit` bootstrap stack and its assets bucket stay. Delete them separately (empty the
bucket first) if nothing else in the account uses CDK.

## GPU notes: CUDA in `backend/uv.lock`

`backend/uv.lock` pins `torch 2.14.1`. The PyPI wheel `torch-2.14.1-cp312-cp312-manylinux_2_28_x86_64.whl`
pulls CUDA on Linux (`sys_platform == 'linux'` markers):

- `cuda-toolkit 13.0.3` with cuBLAS, cuDNN, cuFFT and the other CUDA libraries, plus
  `nvidia-cudnn-cu13`, `nvidia-nccl-cu13`, `nvidia-cusparselt-cu13`, `nvidia-nvshmem-cu13`,
  `nvidia-cuda-runtime 13.0.96`, and `triton`.

The backend image built on the instance is therefore CUDA-enabled, and no backend change is
needed. Two caveats:

- **Driver ≥ 580.** CUDA 13 user-space libraries need NVIDIA driver **580 or newer**. Current
  releases of the DLAMI Base OSS NVIDIA Driver AMI should ship a 580-series driver, but this
  hasn't been checked on a live instance. An older or pinned AMI might not, in which case the bootstrap falls back to `CC_DEVICE=cpu` and logs a warning.
  Check with `nvidia-smi` on the instance. If you need an older driver, rebuild the backend
  against CUDA 12 wheels (the PyTorch `cu126`/`cu128` index) instead.
- **The T4 is Turing (sm_75).** That's still supported by CUDA 13, which dropped Maxwell,
  Pascal and Volta.

---

Part of the [AWS deployment](README.md) documentation.
