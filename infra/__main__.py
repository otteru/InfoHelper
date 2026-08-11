from collections.abc import Mapping

import pulumi
import pulumi_aws as aws

from ecs import create_ecs_resources, create_task_definition
from iam import create_ecs_iam_resources, create_scheduler_iam_resources
from network import create_network_resources
from ssm_parameters import create_secret_parameters
from scheduler import create_daily_schedule

config = pulumi.Config()
repository_name: str = config.require("ecrRepositoryName")
stack: str = pulumi.get_stack()
sender_email: pulumi.Output[str] = config.require_secret("sesSenderEmail")
vpc_cidr: str = config.require("vpcCidr")
common_tags: Mapping[str, str] = {
    "Project": "info-helper",
    "Environment": stack,
    "ManagedBy": "Pulumi",
}
google_api_key: pulumi.Output[str] = config.require_secret("googleApiKey")
supabase_secret_key: pulumi.Output[str] = config.require_secret("supabaseSecretKey")
image_tag: str = config.require("imageTag")
recipient_email: pulumi.Output[str] = config.require_secret("recipientEmail")

aws_config = pulumi.Config("aws")
aws_region: str = aws_config.require("region")
supabase_project_id: str = config.require("supabaseProjectId")

# scheduler 관련
schedule_expression: str = config.require("scheduleExpression")
schedule_timezone: str = config.require("scheduleTimezone")
schedule_state: str = config.require("scheduleState")

# ECR
repository = aws.ecr.Repository(
    "app-repository",
    name=repository_name,
    # 이미 존재하는 이미지 태그를 다른 이미지에 덮어쓸 수 없도록 설정합니다.
    image_tag_mutability="IMMUTABLE",
    # 이미지가 있으면 Repository 삭제 금지
    force_delete=False,
    # ECR Repository에 저장되는 Docker 이미지 데이터를 어떤 방식으로 암호화할지 설정합니다.
    # AES256은 AWS가 관리하는 S3 암호화 키를 사용하여 저장 데이터를 암호화한다는 의미
    encryption_configurations=[{"encryption_type": "AES256"}],
    tags=common_tags,
)

# SES V2
sender_identity = aws.sesv2.EmailIdentity(
    "sender_identity",
    email_identity=sender_email,
    # Pulumi가 해당 리소스를 실수로 삭제하지 못하게 보호
    opts=pulumi.ResourceOptions(protect=True),
)

# 이렇게 create.. 함수를 계속 호출을 해도 리소스 타입 + Pulumi 논리 이름 + Parent로 식별하기에
# 이게 같으면 변경이 없다. (물론 속성이 변경된 경우는 Update를 진행)
network = create_network_resources(
    stack=stack,
    vpc_cidr=vpc_cidr,
    common_tags=common_tags,
)

ecs = create_ecs_resources(stack=stack, common_tags=common_tags)

secret_parameters = create_secret_parameters(
    stack=stack,
    google_api_key=google_api_key,
    supabase_secret_key=supabase_secret_key,
    common_tags=common_tags,
)

ecs_iam = create_ecs_iam_resources(
    stack=stack,
    sender_identity_arn=sender_identity.arn,
    ssm_parameter_arns=(
        secret_parameters.google_api_key_parameter.arn,
        secret_parameters.supabase_secret_key_parameter.arn,
    ),
    common_tags=common_tags,
)

# task
task_definition = create_task_definition(
    stack=stack,
    repository_url=repository.repository_url,
    image_tag=image_tag,
    task_execution_role_arn=ecs_iam.task_execution_role.arn,
    task_role_arn=ecs_iam.task_role.arn,
    log_group_name=ecs.log_group.name,
    aws_region=aws_region,
    supabase_project_id=supabase_project_id,
    sender_email=sender_email,
    recipient_email=recipient_email,
    google_api_key_parameter_arn=(
        secret_parameters.google_api_key_parameter.arn
    ),
    supabase_secret_key_parameter_arn=(
        secret_parameters.supabase_secret_key_parameter.arn
    ),
    common_tags=common_tags,
)

# EventBridge Scheduler
scheduler_iam = create_scheduler_iam_resources(
    stack=stack,
    cluster_arn=ecs.cluster.arn,
    task_definition_arn=task_definition.arn,
    ecs_role_arns=(
        # ECS가 컨테이너를 준비 및 관리
        ecs_iam.task_execution_role.arn,
        # 컨테이너 내부 애플리케이션이 사용
        ecs_iam.task_role.arn,
    ),
    common_tags=common_tags,
)

daily_schedule = create_daily_schedule(
    stack=stack,
    cluster_arn=ecs.cluster.arn,
    task_definition_arn=task_definition.arn,
    # Scheduler가 ECS RunTask를 호출할 때 사용할 Role
    scheduler_role_arn=scheduler_iam.execution_role.arn,
    subnet_ids=tuple(subnet.id for subnet in network.public_subnets),
    security_group_id=network.ecs_task_security_group.id,
    schedule_expression=schedule_expression,
    schedule_timezone=schedule_timezone,
    schedule_state=schedule_state,
)

pulumi.export("ecr_repository_url", repository.repository_url)
pulumi.export("ses_identity_arn", sender_identity.arn)
pulumi.export("vpc_id", network.vpc.id)
pulumi.export(
    "public_subnet_ids",
    [subnet.id for subnet in network.public_subnets],
)
pulumi.export(
    "ecs_task_security_group_id",
    network.ecs_task_security_group.id,
)
pulumi.export("ecs_cluster_arn", ecs.cluster.arn)
pulumi.export("ecs_log_group_name", ecs.log_group.name)
pulumi.export(
    "ecs_task_execution_role_arn",
    ecs_iam.task_execution_role.arn,
)
pulumi.export("ecs_task_role_arn", ecs_iam.task_role.arn)
pulumi.export("ecs_task_definition_arn", task_definition.arn)
