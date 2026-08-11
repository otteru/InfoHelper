from collections.abc import Mapping
from dataclasses import dataclass

import pulumi
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


def create_task_definition(
    *,
    stack: str,
    repository_url: pulumi.Input[str],
    image_tag: str,
    task_execution_role_arn: pulumi.Input[str],
    task_role_arn: pulumi.Input[str],
    log_group_name: pulumi.Input[str],
    aws_region: str,
    supabase_project_id: str,
    sender_email: pulumi.Input[str],
    recipient_email: pulumi.Input[str],
    google_api_key_parameter_arn: pulumi.Input[str],
    supabase_secret_key_parameter_arn: pulumi.Input[str],
    common_tags: Mapping[str, str],
) -> aws.ecs.TaskDefinition:
    # ECR Repository 주소와 변경 불가능한 Commit SHA 태그를 결합해 실행 이미지를 지정
    image_uri: pulumi.Output[str] = pulumi.Output.format(
        "{}:{}",
        repository_url,
        image_tag,
    )

    # ECS API가 요구하는 JSON 문자열로 컨테이너 실행 설정을 직렬화
    # Output 값은 실제 ARN과 이메일 등이 결정된 뒤 Pulumi가 안전하게 치환
    container_definitions: pulumi.Output[str] = pulumi.Output.json_dumps(
        [
            {
                "name": "info-helper",
                "image": image_uri,
                # 필수 컨테이너가 종료되면 ECS Task도 종료
                "essential": True,
                # 인증정보가 아닌 일반 실행 설정을 환경변수로 전달
                "environment": [
                    {
                        "name": "SUPABASE_PROJECT_ID",
                        "value": supabase_project_id,
                    },
                    {
                        "name": "AWS_REGION",
                        "value": aws_region,
                    },
                    {
                        "name": "SES_SENDER_EMAIL",
                        "value": sender_email,
                    },
                    {
                        "name": "RECIPIENT_EMAIL",
                        "value": recipient_email,
                    },
                ],
                # 민감정보는 평문 대신 SSM Parameter ARN으로 참조
                "secrets": [
                    {
                        "name": "GOOGLE_API_KEY",
                        "valueFrom": google_api_key_parameter_arn,
                    },
                    {
                        "name": "SUPABASE_SECRET_KEY",
                        "valueFrom": supabase_secret_key_parameter_arn,
                    },
                ],
                # 컨테이너의 표준 출력과 오류 출력을 CloudWatch Logs로 전송
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": log_group_name,
                        "awslogs-region": aws_region,
                        "awslogs-stream-prefix": "info-helper",
                    },
                },
            }
        ]
    )

    return aws.ecs.TaskDefinition(
        "app-task-definition",
        # Task Definition의 버전들을 묶는 이름
        family=f"info-helper-{stack}",
        # EC2 인스턴스 없이 AWS Fargate에서 실행
        requires_compatibilities=["FARGATE"],
        # Fargate Task마다 독립적인 ENI를 사용하기 위한 필수 네트워크 모드
        network_mode="awsvpc",
        # Chromium 크롤링 작업의 시작 사양: 1 vCPU, 2GB 메모리
        cpu="1024",
        memory="2048",
        # ECS 에이전트가 ECR, CloudWatch Logs, SSM을 사용할 때 맡는 Role
        execution_role_arn=task_execution_role_arn,
        # 컨테이너 애플리케이션이 SES를 호출할 때 맡는 Role
        task_role_arn=task_role_arn,
        # ECR에 Push한 linux/amd64 이미지와 실행 환경을 일치시킴
        runtime_platform={
            "cpu_architecture": "X86_64",
            "operating_system_family": "LINUX",
        },
        container_definitions=container_definitions,
        tags=common_tags,
    )
