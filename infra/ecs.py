from collections.abc import Mapping
from dataclasses import dataclass

import pulumi_aws as aws


@dataclass(frozen=True)
class EcsResources:
    cluster: aws.ecs.Cluster
    log_group: aws.cloudwatch.LogGroup


def create_ecs_resources(
    *,
    stack: str,
    common_tags: Mapping[str, str],
) -> EcsResources:
    # ECS
    ecs_cluster = aws.ecs.Cluster(
        "app-cluster",
        name=f"info-helper-{stack}",
        tags=common_tags,
    )

    # CloudWatch Logs
    ecs_log_group = aws.cloudwatch.LogGroup(
        "ecs-log-group",
        name=f"/ecs/info-helper-{stack}",
        # 14일 뒤에 로그 삭제
        retention_in_days=14,
        tags=common_tags,
    )

    return EcsResources(cluster=ecs_cluster, log_group=ecs_log_group)
