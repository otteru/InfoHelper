"""공고별 필터링 메타데이터 v1 스키마."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


EmploymentType = Literal[
    'full_time',  # 정규직
    'contract',  # 계약직
    'freelance',  # 프리랜서
    'intern_experience',  # 체험형 인턴
    'intern_conversion',  # 전환형 인턴
    'military_alternative',  # 병역특례
]


class Experience(BaseModel):
    """공고의 최소·최대 요구 경력 연수."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    min_years: int | None = Field(ge=0, description='최소 경력 연수. 정보가 없으면 null')
    max_years: int | None = Field(ge=0, description='최대 경력 연수. 명시되지 않으면 null')


class DocumentMetadata(BaseModel):
    """공고 ID로 원본 corpus와 연결하는 필터링 메타데이터."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    doc_id: UUID
    job_roles: tuple[str, ...] = Field(description='공고에 나온 원본 직무명')
    regions: tuple[str, ...] = Field(description='서울, 경기, 경남, 경북, 부산 등 광역 지역명 또는 기타(해외)')
    employment_types: tuple[EmploymentType, ...]
    experience: Experience
    skills: tuple[str, ...] = Field(description='공고에 명시된 기술명')
