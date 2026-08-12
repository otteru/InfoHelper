from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pulumi
import pulumi_aws as aws


@dataclass(frozen=True)
class GitHubOidcResources:
    provider: aws.iam.OpenIdConnectProvider
    preview_role: aws.iam.Role
    deploy_role: aws.iam.Role


def _create_assume_role_policy(
    *,
    # GitHub OIDC Provider의 ARN
    provider_arn: pulumi.Input[str],
    subject: str,
) -> pulumi.Output[str]:
    """특정 GitHub Actions 실행만 IAM Role을 사용할 수 있게 한다."""

    # JSON 안에 Pulumi Output 값이 들어가므로 Output.json_dumps를 사용한다.
    return pulumi.Output.json_dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    # GitHub라는 AWS 외부 Identity Provider를 믿는 거라서 Federated 사용
                    "Principal": {
                        "Federated": provider_arn,
                    },
                    "Action": "sts:AssumeRoleWithWebIdentity",
                    "Condition": {
                        "StringEquals": {
                            # aud는 Audience로 누굴 위해 발급된 토큰인지를 나타낸다.
                            "token.actions.githubusercontent.com:aud": (
                                "sts.amazonaws.com"
                            ),
                            # sub는 Subject로 이 토큰의 실제 주체가 누구인지를 나타낸다.
                            "token.actions.githubusercontent.com:sub": subject,
                        }
                    },
                }
            ],
        }
    )


def create_github_oidc_resources(
    *,
    stack: str,
    github_repository: str,
    github_environment: str,
    managed_role_arns: Sequence[pulumi.Input[str]],
    common_tags: Mapping[str, str],
) -> GitHubOidcResources:
    """GitHub Actions가 사용할 OIDC Provider와 IAM Role을 생성한다."""

    provider = aws.iam.OpenIdConnectProvider(
        "github-oidc-provider",
        # sub
        url="https://token.actions.githubusercontent.com",
        # aud - STS는 Security Token Service의 약자로, AWS에서 임시 보안 자격 증명
        client_id_lists=["sts.amazonaws.com"],
        tags=common_tags,
    )

    preview_assume_role_policy = _create_assume_role_policy(
        provider_arn=provider.arn,
        subject=f"repo:{github_repository}:pull_request",
    )

    preview_role = aws.iam.Role(
        "github-preview-role",
        name=f"info-helper-{stack}-github-preview-role",
        assume_role_policy=preview_assume_role_policy,
        tags=common_tags,
    )

    deploy_assume_role_policy = _create_assume_role_policy(
        provider_arn=provider.arn,
        subject=(
            f"repo:{github_repository}:"
            f"environment:{github_environment}"
        ),
    )

    deploy_role = aws.iam.Role(
        "github-deploy-role",
        name=f"info-helper-{stack}-github-deploy-role",
        assume_role_policy=deploy_assume_role_policy,
        tags=common_tags,
    )

    # PR의 Pulumi Preview는 AWS 리소스 조회만 허용
    aws.iam.RolePolicyAttachment(
        "github-preview-read-only-policy",
        role=preview_role.name,
        policy_arn="arn:aws:iam::aws:policy/ReadOnlyAccess",
    )

    # Pulumi Up이 IAM 외의 AWS 리소스를 관리할 수 있도록 허용
    aws.iam.RolePolicyAttachment(
        "github-deploy-power-user-policy",
        role=deploy_role.name,
        policy_arn="arn:aws:iam::aws:policy/PowerUserAccess",
    )

    aws.iam.RolePolicyAttachment(
        "github-deploy-read-only-policy",
        role=deploy_role.name,
        policy_arn="arn:aws:iam::aws:policy/ReadOnlyAccess",
    )

    deploy_iam_policy: pulumi.Output[str] = pulumi.Output.json_dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    # 내가 직접 이 Role을 사용하는 건 아니지만, AWS 서비스에게 이 Role을 사용하라고 넘겨줄 수 있는 권한
                    "Sid": "PassProjectRuntimeRoles",
                    "Effect": "Allow",
                    "Action": ["iam:PassRole"],
                    "Resource": list(managed_role_arns),
                    "Condition": {
                        "StringEquals": {
                            "iam:PassedToService": [
                                "ecs-tasks.amazonaws.com",
                                "scheduler.amazonaws.com",
                            ]
                        }
                    },
                },
            ],
        }
    )

    aws.iam.RolePolicy(
        "github-deploy-iam-policy",
        role=deploy_role.id,
        policy=deploy_iam_policy,
    )

    return GitHubOidcResources(
        provider=provider,
        preview_role=preview_role,
        deploy_role=deploy_role,
    )
