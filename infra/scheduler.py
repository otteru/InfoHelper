from collections.abc import Sequence

import pulumi
import pulumi_aws as aws


def create_daily_schedule(
    *,
    stack: str,
    cluster_arn: pulumi.Input[str],
    task_definition_arn: pulumi.Input[str],
    scheduler_role_arn: pulumi.Input[str],
    subnet_ids: Sequence[pulumi.Input[str]],
    security_group_id: pulumi.Input[str],
    schedule_expression: str,
    schedule_timezone: str,
    schedule_state: str,
) -> aws.scheduler.Schedule:
    """ECS Fargate Task를 매일 실행하는 Schedule을 생성한다."""

    return aws.scheduler.Schedule(
        # Pulumi 내부 이름
        "daily-ecs-task-schedule",
        # AWS에서 생성되는 리소스 이름
        name=f"info-helper-{stack}-daily",
        description="InfoHelper 추천 이메일 배치 실행",
        schedule_expression=schedule_expression,
        schedule_expression_timezone=schedule_timezone,
        state=schedule_state,
        flexible_time_window={
            "mode": "OFF",
        },
        target={
            # ECS Task가 실행될 Cluster
            "arn": cluster_arn,
            # Scheduler 자신이 RunTask를 호출할 때 사용할 Role
            "role_arn": scheduler_role_arn,
            "ecs_parameters": {
                "task_definition_arn": task_definition_arn,
                "launch_type": "FARGATE",
                "platform_version": "LATEST",
                "task_count": 1,
                "network_configuration": {
                    "subnets": list(subnet_ids),
                    "security_groups": [security_group_id],
                    "assign_public_ip": True,
                },
            },
        },
    )
