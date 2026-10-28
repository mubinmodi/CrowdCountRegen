# Continuous deployment

`.github/workflows/deploy.yml` runs after **CI** passes on `main`, or by hand
(*Actions → Deploy → Run workflow*):

```
CI passes on main → plan: cdk diff (read-only) → approval → deploy: cdk deploy → summary
```

- **No AWS keys in GitHub.** Each job asks GitHub for an OIDC token and exchanges it for a
  1-hour session. AWS only accepts the token for this repository's `aws-plan` and
  `production` environments.
- **The plan role** can only assume CDK's read-only lookup role, enough for
  `cdk diff --no-change-set`. The diff goes in the run summary, so the reviewer sees exactly
  what they're approving.
- **The deploy role** can only assume CDK's deploy, asset-publishing and lookup roles.
  CloudFormation makes the changes, not the workflow.
- **Approval** is the `production` environment's required reviewers: the deploy job waits
  until someone approves it in GitHub.
- **Safe rollouts.** The deploy waits for the new instance's health signal. If it never
  arrives, CloudFormation rolls back and the old instance keeps serving. Deploys never
  overlap (`concurrency`). To roll back a bad release, revert the commit on `main`, which
  deploys the previous code the same way.

Until the two role variables exist, the workflow skips both jobs, so it is safe to have in
the repo before AWS is set up.

## One-time setup

1. Deploy the roles (by hand, once):

   ```bash
   cd infra
   npx aws-cdk@2 deploy ZonewatchGithubDeploy --profile <p>
   # If the account already has a GitHub OIDC provider:
   #   -c zonewatch:githubOidcProviderArn=arn:aws:iam::<account>:oidc-provider/token.actions.githubusercontent.com
   ```

2. Create the two environments. Only `main` may use them, and `production` needs your
   approval:

   ```bash
   me=$(gh api user --jq .id)
   for env in aws-plan production; do
     reviewers='[]'
     [ "$env" = production ] && reviewers="[{\"type\": \"User\", \"id\": $me}]"
     gh api -X PUT "repos/mubinmodi/Zonewatch/environments/$env" --input - <<JSON
   {"reviewers": $reviewers,
    "deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
   JSON
     gh api -X POST "repos/mubinmodi/Zonewatch/environments/$env/deployment-branch-policies" \
       -f name=main
   done
   ```

   (Or in GitHub: *Settings → Environments*. Add yourself as a required reviewer on
   `production`, and limit both to the `main` branch.)

3. Store the role ARNs from step 1's outputs as repository variables (they aren't secrets):

   ```bash
   gh variable set AWS_PLAN_ROLE_ARN --body <PlanRoleArn>
   gh variable set AWS_DEPLOY_ROLE_ARN --body <DeployRoleArn>
   ```

The next merge to `main` then plans automatically and waits for your approval to deploy.

---

Part of the [AWS deployment](README.md) documentation.
