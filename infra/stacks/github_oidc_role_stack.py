"""Stack provisioning an IAM role for GitHub Actions OIDC deployments."""

from __future__ import annotations

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct


class GithubOidcRoleStack(Stack):
    """Create an IAM role assumable via GitHub Actions OIDC for CI/CD deployments."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        github_owner: str,
        github_repo: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        provider = iam.OpenIdConnectProvider(
            self,
            "GitHubProvider",
            url="https://token.actions.githubusercontent.com",
            client_ids=["sts.amazonaws.com"],
            thumbprints=["6938fd4d98bab03faadb97b34396831e3780aea1"],
        )

        role = iam.Role(
            self,
            "GithubActionsRole",
            role_name="AieDxprojectGithubActionsRole",
            assumed_by=iam.OpenIdConnectPrincipal(provider).with_conditions(  # type: ignore[arg-type]
                {
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                    },
                    "StringLike": {
                        "token.actions.githubusercontent.com:sub": (
                            f"repo:{github_owner}/{github_repo}:*"
                        )
                    },
                }
            ),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonEC2ContainerRegistryPowerUser"
                ),
            ],
        )

        role.add_to_policy(
            iam.PolicyStatement(
                sid="AllowEcsDeploymentUpdates",
                actions=[
                    "ecs:DescribeClusters",
                    "ecs:DescribeServices",
                    "ecs:DescribeTaskDefinition",
                    "ecs:DescribeTasks",
                    "ecs:ListServices",
                    "ecs:ListTaskDefinitions",
                    "ecs:RegisterTaskDefinition",
                    "ecs:UpdateService",
                    "iam:PassRole",
                ],
                resources=["*"],
            )
        )

        CfnOutput(
            self,
            "GithubActionsRoleArn",
            value=role.role_arn,
            description="IAM Role ARN to configure as AWS_DEPLOY_ROLE_ARN in GitHub secrets.",
        )
