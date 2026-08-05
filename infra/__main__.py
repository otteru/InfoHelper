import pulumi
import pulumi_aws as aws


config = pulumi.Config()
repository_name: str = config.require("ecrRepositoryName")
stack: str = pulumi.get_stack()
sender_email: pulumi.Output[str] = config.require_secret("sesSenderEmail")
vpc_cidr: str = config.require("vpcCidr")

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
    encryption_configurations=[
        {
            "encryption_type": "AES256",
        }
    ],
    tags={
        "Project": "info-helper",
        "Environment": stack,
        "ManagedBy": "Pulumi",
    },
)

# SES V2
sender_identity = aws.sesv2.EmailIdentity(
    "sender_identity",
    email_identity=sender_email,
    # Pulumi가 해당 리소스를 실수로 삭제하지 못하게 보호
    opts=pulumi.ResourceOptions(protect=True),
)

# Network
vpc = aws.ec2.Vpc(
    "app-vpc",
    # VPC가 사용할 사설 IPv4 주소 범위
    cidr_block=vpc_cidr,
    # VPC 안에서 AWS가 제공하는 DNS 서버인 Route 53 Resolver를 이용한 DNS 이름 해석을 허용
    enable_dns_support=True,
    # VPC 안의 지원되는 리소스가 AWS가 제공하는 DNS 호스트 이름을 받을 수 있도록 허용
    enable_dns_hostnames=True,
    tags={
        "Name": f"info-helper-{stack}-vpc",
        "Project": "info-helper",
        "Environment": stack,
        "ManagedBy": "Pulumi",
    },
)

# Gateway
# TODO: Route Table 설정
internet_gateway = aws.ec2.InternetGateway(
    "app-internet-gateway",
    vpc_id=vpc.id,
    tags={
        "Name": f"info-helper-{stack}-igw",
        "Project": "info-helper",
        "Environment": stack,
        "ManagedBy": "Pulumi",
    },
)

pulumi.export("ecr_repository_url", repository.repository_url)
pulumi.export("ses_identity_arn", sender_identity.arn)
pulumi.export("vpc_id", vpc.id)
