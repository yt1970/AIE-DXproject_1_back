from aws_cdk import App, assertions

from infra.stacks.backend_stack import AieDxprojectBackendStack
from infra.stacks.github_oidc_role_stack import GithubOidcRoleStack


def test_stack_synthesizes() -> None:
    app = App(
        context={
            "account": "111111111111",
            "region": "ap-northeast-1",
            "github_owner": "example",
            "github_repo": "aie-dxproject",
        }
    )

    backend_stack = AieDxprojectBackendStack(app, "TestBackendStack")
    oidc_stack = GithubOidcRoleStack(
        app,
        "TestGithubOidcStack",
        github_owner="example",
        github_repo="aie-dxproject",
    )

    backend_template = assertions.Template.from_stack(backend_stack)
    backend_template.resource_count_is("AWS::ECS::Cluster", 1)
    backend_template.resource_count_is("AWS::ECR::Repository", 1)

    oidc_template = assertions.Template.from_stack(oidc_stack)
    oidc_template.has_resource_properties(
        "AWS::IAM::Role",
        assertions.Match.object_like(
            {
                "AssumeRolePolicyDocument": assertions.Match.object_like(
                    {
                        "Statement": assertions.Match.array_with(
                            [
                                assertions.Match.object_like(
                                    {
                                        "Condition": assertions.Match.object_like(
                                            {
                                                "StringEquals": assertions.Match.object_like(
                                                    {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"}
                                                )
                                            }
                                        )
                                    }
                                )
                            ]
                        )
                    }
                )
            }
        ),
    )
