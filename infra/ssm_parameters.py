from collections.abc import Mapping
from dataclasses import dataclass

import pulumi
import pulumi_aws as aws


@dataclass(frozen=True)
class SecretParameters:
    google_api_key_parameter: aws.ssm.Parameter
    supabase_secret_key_parameter: aws.ssm.Parameter


def create_secret_parameters(
    # *는 그 뒤에 나오는 파라미터는 반드시 이름을 붙여서 전달하라는 뜻
    *,
    stack: str,
    google_api_key: pulumi.Input[str],
    supabase_secret_key: pulumi.Input[str],
    common_tags: Mapping[str, str],
) -> SecretParameters:
    google_api_key_parameter = aws.ssm.Parameter(
        "google-api-key-parameter",
        name=f"/info-helper/{stack}/google-api-key",
        description="Info Helper Google API Key",
        type=aws.ssm.ParameterType.SECURE_STRING,
        value=google_api_key,
        tags=common_tags,
    )

    supabase_secret_key_parameter = aws.ssm.Parameter(
        "supabase-secret-key-parameter",
        name=f"/info-helper/{stack}/supabase-secret-key",
        description="Info Helper Supabase Secret Key",
        type=aws.ssm.ParameterType.SECURE_STRING,
        value=supabase_secret_key,
        tags=common_tags,
    )

    return SecretParameters(
        google_api_key_parameter=google_api_key_parameter,
        supabase_secret_key_parameter=supabase_secret_key_parameter,
    )
