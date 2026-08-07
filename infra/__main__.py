from collections.abc import Mapping

import pulumi
import pulumi_aws as aws

from ecs import create_ecs_resources
from iam import create_ecs_iam_resources
from network import create_network_resources


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

network = create_network_resources(
    stack=stack,
    vpc_cidr=vpc_cidr,
    common_tags=common_tags,
)
ecs = create_ecs_resources(stack=stack, common_tags=common_tags)
ecs_iam = create_ecs_iam_resources(
    stack=stack,
    sender_identity_arn=sender_identity.arn,
    common_tags=common_tags,
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
