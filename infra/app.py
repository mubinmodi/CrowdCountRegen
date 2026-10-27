"""CDK entry point: `npx aws-cdk@2 synth` / `deploy` run this through `uv run python app.py`."""

import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

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

cdk.Tags.of(app).add("Project", "CrowdCounting")
cdk.Validations.of(app).add_plugins(AwsSolutionsChecks(app))

app.synth()
