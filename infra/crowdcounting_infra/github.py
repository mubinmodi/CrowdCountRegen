"""IAM roles that GitHub Actions assumes through OIDC: no long-lived AWS keys in GitHub.

Two roles, each trusted only for one GitHub *environment* of one repository:

- plan (environment `aws-plan`): may only assume CDK's lookup role, which is read-only.
  Enough for `cdk diff --no-change-set`.
- deploy (environment `production`): may assume CDK's deploy, file-publishing and lookup
  roles, which is what `cdk deploy` needs. The `production` environment carries the manual
  approval (required reviewers), so this role can't be used without a human saying yes.

Neither role gets permissions on resources directly. Everything goes through the roles that
`cdk bootstrap` created, which CloudFormation then uses to change the stack.
"""

import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from constructs import Construct

GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"


class GithubDeployStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        repository: str,
        provider_arn: str = "",
        qualifier: str = "hnb659fds",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # An account can have one provider per URL: reuse an existing one when given.
        if provider_arn:
            provider: iam.IOidcProvider = iam.OidcProviderNative.from_oidc_provider_arn(
                self, "GithubOidc", provider_arn
            )
        else:
            provider = iam.OidcProviderNative(
                self,
                "GithubOidc",
                url=GITHUB_OIDC_URL,
                client_ids=["sts.amazonaws.com"],
            )

        def cdk_role(kind: str) -> str:
            return (
                f"arn:{self.partition}:iam::{self.account}:role/"
                f"cdk-{qualifier}-{kind}-role-{self.account}-{self.region}"
            )

        def github_role(role_id: str, environment: str, cdk_roles: list[str], about: str):
            role = iam.Role(
                self,
                role_id,
                description=about,
                max_session_duration=cdk.Duration.hours(1),
                assumed_by=iam.FederatedPrincipal(
                    provider.oidc_provider_arn,
                    conditions={
                        "StringEquals": {
                            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                            # Only jobs running in this environment of this repository.
                            "token.actions.githubusercontent.com:sub": (
                                f"repo:{repository}:environment:{environment}"
                            ),
                        }
                    },
                    assume_role_action="sts:AssumeRoleWithWebIdentity",
                ),
            )
            role.add_to_policy(
                iam.PolicyStatement(
                    actions=["sts:AssumeRole", "sts:TagSession"],
                    resources=[cdk_role(kind) for kind in cdk_roles],
                )
            )
            return role

        plan = github_role(
            "PlanRole",
            "aws-plan",
            ["lookup"],
            f"GitHub Actions ({repository}, environment aws-plan): read-only cdk diff",
        )
        deploy = github_role(
            "DeployRole",
            "production",
            ["deploy", "file-publishing", "lookup"],
            f"GitHub Actions ({repository}, environment production): cdk deploy after approval",
        )

        cdk.CfnOutput(
            self,
            "PlanRoleArn",
            value=plan.role_arn,
            description="GitHub variable AWS_PLAN_ROLE_ARN",
        )
        cdk.CfnOutput(
            self,
            "DeployRoleArn",
            value=deploy.role_arn,
            description="GitHub variable AWS_DEPLOY_ROLE_ARN",
        )
