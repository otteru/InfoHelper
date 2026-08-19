from enum import Enum
from typing import Literal

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
