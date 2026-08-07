from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pulumi
import pulumi_aws as aws


@dataclass(frozen=True)
class EcsIamResources:
    task_execution_role: aws.iam.Role
    task_role: aws.iam.Role


def create_ecs_iam_resources(
    *,
    stack: str,
    sender_identity_arn: pulumi.Input[str],
    ssm_parameter_arns: Sequence[pulumi.Input[str]],
    common_tags: Mapping[str, str],
) -> EcsIamResources:
    # ECS IAM Roles
    ecs_task_assume_role_policy = aws.iam.get_policy_document(
        statements=[
            {
                # 아래 동작을 허용
                "effect": "Allow",
                # IAM Role을 Assume(맡아서 사용)할 수 있도록 허용
                "actions": ["sts:AssumeRole"],
                # 누가 이 Role을 Assume할 수 있는지 지정
                "principals": [
                    {
                        # AWS 서비스에게 권한 부여
                        "type": "Service",
                        # ECS Task 서비스만 이 Role을 사용할 수 있도록 허용
                        "identifiers": ["ecs-tasks.amazonaws.com"],
                    }
                ],
            }
        ]
    )

    # IAM - execution role
    ecs_task_execution_role = aws.iam.Role(
        "ecs-task-execution-role",
        name=f"info-helper-{stack}-ecs-task-execution-role",
        assume_role_policy=ecs_task_assume_role_policy.json,
        tags=common_tags,
    )

    ecs_task_execution_policy_attachment = aws.iam.RolePolicyAttachment(
        "ecs-task-execution-policy-attachment",
        role=ecs_task_execution_role.name,
        # ECR 이미지 Pull, CloudWatch 로그
        policy_arn=(
            "arn:aws:iam::aws:policy/service-role/"
            "AmazonECSTaskExecutionRolePolicy"
        ),
    )

    # IAM - task role
    ecs_task_role = aws.iam.Role(
        "ecs-task-role",
        name=f"info-helper-{stack}-ecs-task-role",
        assume_role_policy=ecs_task_assume_role_policy.json,
        tags=common_tags,
    )

    # custom으로 ecs_task_role를 위해 ses 접근 권한 생성
    ses_send_policy_json: pulumi.Output[str] = pulumi.Output.json_dumps(
        {
            # IAM Policy 문법의 버전
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["ses:SendEmail"],
                    "Resource": sender_identity_arn,
                }
            ],
        }
    )

    # ECS가 Task 시작 전에 SSM Parameter를 읽을 수 있도록 허용
    ssm_read_policy_json: pulumi.Output[str] = pulumi.Output.json_dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["ssm:GetParameters"],
                    "Resource": list(ssm_parameter_arns),
                }
            ],
        }
    )

    # custom 생성한 정책 적용 - aws가 제공하는 권한이 아니기에 attachment가 아님
    ecs_task_ses_inline_policy = aws.iam.RolePolicy(
        "ecs-task-ses-policy",
        role=ecs_task_role.id,
        policy=ses_send_policy_json,
    )

    ecs_execution_ssm_inline_policy = aws.iam.RolePolicy(
        "ecs-execution-ssm-policy",
        role=ecs_task_execution_role.id,
        policy=ssm_read_policy_json,
    )

    return EcsIamResources(
        task_execution_role=ecs_task_execution_role,
        task_role=ecs_task_role,
    )
