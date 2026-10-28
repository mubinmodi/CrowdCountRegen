# 0010. Deploy from GitHub Actions with OIDC roles and a manual approval

**Status:** Accepted

## Context

Deploying by hand from a laptop works, but it deploys whatever is in the working tree,
depends on one person's credentials, and leaves no record of what was approved. The usual
alternative, AWS access keys stored as GitHub secrets, means long-lived credentials that can
leak and are rarely rotated.

## Decision

- `.github/workflows/deploy.yml` runs after **CI** passes on `main` (or by hand) and deploys
  the exact commit CI tested.
- **OIDC, no stored keys.** Each job exchanges a GitHub-issued token for a one-hour AWS
  session. The roles (`infra/zonewatch_infra/github.py`) trust only
  `repo:mubinmodi/Zonewatch:environment:<name>`, so a fork, another branch's workflow,
  or another repository can't assume them.
- **Two roles, two environments.** `aws-plan` may only assume CDK's read-only lookup role and
  runs `cdk diff --no-change-set`, posting the diff to the run summary. `production` may
  assume CDK's deploy, file-publishing and lookup roles. Neither has direct resource
  permissions: CloudFormation, through the bootstrap roles, makes the changes.
- **Manual approval** is the `production` environment's required reviewers. The deploy job
  waits until a reviewer approves, after reading the diff.
- **Safety:** deploys never overlap (a concurrency group that never cancels), a new instance
  must pass its health check or CloudFormation rolls back, and rolling back a release means
  reverting the commit.
- The workflow skips itself until the role ARNs are configured, so it is safe in the repo
  before AWS exists.

## Consequences

- What runs in production is a reviewed diff of a tested commit, with an audit trail in
  GitHub (who approved, which commit) and CloudTrail (which role did what).
- The roles stack is deployed once by hand: something has to create the first trust.
- GitHub environments and their reviewers are repository settings, not code; the setup
  commands are in [Continuous deployment](../aws/ci-cd.md#one-time-setup).
