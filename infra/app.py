#!/usr/bin/env python3
"""CDK application entrypoint for the AIE-DXproject backend infrastructure."""

from __future__ import annotations

import os

import aws_cdk as cdk

from infra.stacks.backend_stack import AieDxprojectBackendStack
from infra.stacks.github_oidc_role_stack import GithubOidcRoleStack


app = cdk.App()

account = app.node.try_get_context("account") or os.getenv("CDK_DEFAULT_ACCOUNT")
region = app.node.try_get_context("region") or os.getenv("CDK_DEFAULT_REGION")

AieDxprojectBackendStack(
    app,
    "AieDxprojectBackendStack",
    env=cdk.Environment(account=account, region=region),
)

github_owner = app.node.try_get_context("github_owner")
github_repo = app.node.try_get_context("github_repo")

if github_owner and github_repo:
    GithubOidcRoleStack(
        app,
        "AieDxprojectGithubOidcStack",
        github_owner=github_owner,
        github_repo=github_repo,
        env=cdk.Environment(account=account, region=region),
    )
else:
    app.node.add_warning(
        "Skipping GithubOidcRoleStack deployment; set context 'github_owner' and 'github_repo' to enable."
    )

app.synth()
