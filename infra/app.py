"""CDK entry point: `npx aws-cdk@2 synth` / `deploy` run this through `uv run python app.py`."""

import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

from crowdcounting_infra.github import GithubDeployStack
from crowdcounting_infra.stack import CrowdCountingStack

app = cdk.App()

CrowdCountingStack(
    app,
    "CrowdCounting",
    description="CrowdCounting demo: one GPU instance behind CloudFront",
    # Region only: the account comes from the deploy credentials, and leaving it unresolved
    # keeps synth free of AWS lookups (AZs and the AMI are resolved by CloudFormation).
    env=cdk.Environment(region="us-east-1"),
)

# Deployed once by hand (it creates the roles the deploy workflow uses), then left alone:
#   npx aws-cdk@2 deploy CrowdCountingGithubDeploy
GithubDeployStack(
    app,
    "CrowdCountingGithubDeploy",
    description="CrowdCounting: IAM roles GitHub Actions assumes through OIDC to deploy",
    env=cdk.Environment(region="us-east-1"),
    repository=str(app.node.try_get_context("crowdcounting:githubRepository")),
    # Set when the account already has a GitHub OIDC provider (one per URL per account).
    provider_arn=str(app.node.try_get_context("crowdcounting:githubOidcProviderArn") or ""),
)

cdk.Tags.of(app).add("Project", "CrowdCounting")
cdk.Validations.of(app).add_plugins(AwsSolutionsChecks(app))

app.synth()
