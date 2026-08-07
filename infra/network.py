from collections.abc import Mapping
from dataclasses import dataclass

import pulumi_aws as aws


@dataclass(frozen=True)
class NetworkResources:
    vpc: aws.ec2.Vpc
    public_subnets: tuple[aws.ec2.Subnet, ...]
    ecs_task_security_group: aws.ec2.SecurityGroup


def create_network_resources(
    *,
    stack: str,
    vpc_cidr: str,
    common_tags: Mapping[str, str],
) -> NetworkResources:
    # Network
    vpc = aws.ec2.Vpc(
        "app-vpc",
        # VPC가 사용할 사설 IPv4 주소 범위
        cidr_block=vpc_cidr,
        # VPC 안에서 AWS가 제공하는 DNS 서버인 Route 53 Resolver를 이용한 DNS 이름 해석을 허용
        enable_dns_support=True,
        # VPC 안의 지원되는 리소스가 AWS가 제공하는 DNS 호스트 이름을 받을 수 있도록 허용
        enable_dns_hostnames=True,
        tags={"Name": f"info-helper-{stack}-vpc", **common_tags},
    )

    # Gateway
    # TODO: Route Table 설정
    internet_gateway = aws.ec2.InternetGateway(
        "app-internet-gateway",
        vpc_id=vpc.id,
        tags={"Name": f"info-helper-{stack}-igw", **common_tags},
    )

    # Public Subnets
    # 현재 AWS 리전에서 사용 가능한 AZ(Availability Zone) 목록을 조회
    available_zones = aws.get_availability_zones(state="available")

    # subnet 2개 선언
    public_subnet_specs: tuple[tuple[str, str, int], ...] = (
        ("public-subnet-a", "10.0.1.0/24", 0),
        ("public-subnet-b", "10.0.2.0/24", 1),
    )
    public_subnets: tuple[aws.ec2.Subnet, ...] = tuple(
        aws.ec2.Subnet(
            resource_name,
            vpc_id=vpc.id,
            cidr_block=cidr_block,
            availability_zone=available_zones.names[az_index],
            # Subnet에서 생성되는 네트워크 인터페이스에
            # Public IPv4를 자동 할당할 수 있도록 설정
            map_public_ip_on_launch=True,
            tags={
                "Name": f"info-helper-{stack}-{resource_name}",
                **common_tags,
            },
        )
        for resource_name, cidr_block, az_index in public_subnet_specs
    )

    # Public Route Table
    public_route_table = aws.ec2.RouteTable(
        "public-route-table",
        vpc_id=vpc.id,
        tags={
            "Name": f"info-helper-{stack}-public-route-table",
            **common_tags,
        },
    )

    # 외부 트래픽을 Internet Gateway로 전달
    public_internet_route = aws.ec2.Route(
        "public-internet-route",
        route_table_id=public_route_table.id,
        # VPC 내부 목적지가 아닌 모든 IPv4 트래픽은 Internet Gateway로 보내라
        destination_cidr_block="0.0.0.0/0",
        gateway_id=internet_gateway.id,
    )

    # 두 Subnet에 Public Route Table 연결
    public_subnet_a_route_association = aws.ec2.RouteTableAssociation(
        "public-subnet-a-route-association",
        subnet_id=public_subnets[0].id,
        route_table_id=public_route_table.id,
    )

    public_subnet_b_route_association = aws.ec2.RouteTableAssociation(
        "public-subnet-b-route-association",
        subnet_id=public_subnets[1].id,
        route_table_id=public_route_table.id,
    )

    # ECS Task Security Group
    ecs_task_security_group = aws.ec2.SecurityGroup(
        "ecs-task-security-group",
        description="Security group for the Info Helper ECS task",
        vpc_id=vpc.id,
        ingress=[],
        egress=[
            {
                "description": "Allow outbound HTTP traffic",
                "protocol": "tcp",
                "from_port": 80,
                "to_port": 80,
                "cidr_blocks": ["0.0.0.0/0"],
            },
            {
                "description": "Allow outbound HTTPS traffic",
                "protocol": "tcp",
                "from_port": 443,
                "to_port": 443,
                "cidr_blocks": ["0.0.0.0/0"],
            },
        ],
        tags={"Name": f"info-helper-{stack}-ecs-task-sg", **common_tags},
    )

    return NetworkResources(
        vpc=vpc,
        public_subnets=public_subnets,
        ecs_task_security_group=ecs_task_security_group,
    )
