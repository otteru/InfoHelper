from enum import Enum
from typing import Literal
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class RuleStatus(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    RETIRED = "retired"
    REJECTED = "rejected"


class ValidationStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class HealthStatus(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BROKEN = "broken"


class GeneratedBy(str, Enum):
    LEGACY = "legacy"
    MANUAL = "manual"
    LLM = "llm"


# {
#   "name": "공지 목록",
#   "baseSelector": "table tbody tr",
#   "fields": [
#     {
#       "name": "title",
#       "selector": "a[href*='artclView.do']",
#       "type": "text"
#     },
#     {
#       "name": "url",
#       "selector": "a[href*='artclView.do']",
#       "type": "attribute",
#       "attribute": "href"
#     }
#   ]
# }

# CrawlRuleDefinition은 공지 목록 전체를 추출하는 규칙,
# CrawlRuleField는 그 안에서 개별 데이터를 추출하는 규칙


class CrawlRuleField(BaseModel):
    name: str
    selector: str
    # text, attribute 중 하나의 값만 허용
    type: Literal["text", "attribute"]
    attribute: str | None = None

    # @model_validator - 모델 내 여러 필드의 관계를 함께 검증할 때 (반대로는 @field_validator)
    # after - 개별 필드들의 기본 타입 검증 된 후 완성된 객체(self) 가지고 자동 검증
    @model_validator(mode="after")
    def validate_attribute(self) -> "CrawlRuleField":
        if self.type == "attribute" and self.attribute is None:
            raise ValueError("attribute 타입에는 attribute가 필요합니다.")

        return self


class CrawlRuleDefinition(BaseModel):
    name: str
    base_selector: str = Field(alias="baseSelector")
    fields: tuple[CrawlRuleField, ...] = Field(min_length=1)

# ========================= DB ===========================


class SourceCrawlRuleCreate(BaseModel):
    """새 candidate 규칙을 만들기 위해 필요한 입력값."""

    source_id: UUID
    rule_definition: CrawlRuleDefinition
    generated_by: GeneratedBy


class SourceCrawlRuleResponse(BaseModel):
    """source_crawl_rules 테이블에서 조회·저장 후 반환되는 전체 행."""

    id: UUID
    source_id: UUID
    version: int
    rule_schema_version: int
    status: RuleStatus
    validation_status: ValidationStatus
    health_status: HealthStatus | None
    rule_definition: CrawlRuleDefinition
    generated_by: GeneratedBy
    created_at: datetime
    validated_at: datetime | None
    last_health_checked_at: datetime | None

    @model_validator(mode="after")
    def validate_health_status(self) -> "SourceCrawlRuleResponse":
        if self.status is RuleStatus.ACTIVE and self.health_status is None:
            raise ValueError("active 규칙에는 health_status가 필요합니다.")

        if self.status is not RuleStatus.ACTIVE and self.health_status is not None:
            raise ValueError("inactive 규칙의 health_status는 None이어야 합니다.")

        return self