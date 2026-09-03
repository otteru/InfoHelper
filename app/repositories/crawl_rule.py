from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, cast
from uuid import UUID

from postgrest.types import JSON
from supabase import Client

from app.schemas.crawl_rule import (
    HealthStatus,
    RuleStatus,
    SourceCrawlRuleCreate,
    SourceCrawlRuleResponse,
    ValidationStatus,
)


class SourceCrawlRuleRepository(Protocol):
    def create_candidate(
        self, rule: SourceCrawlRuleCreate
    ) -> SourceCrawlRuleResponse: ...

    def get_active(
        self, source_id: UUID
    ) -> SourceCrawlRuleResponse | None: ...

    def update_validation_status(
        self,
        rule_id: UUID,
        status: ValidationStatus,
    ) -> SourceCrawlRuleResponse: ...

    def update_health_status(
        self,
        rule_id: UUID,
        status: HealthStatus,
    ) -> SourceCrawlRuleResponse: ...

    def activate(self, rule_id: UUID) -> SourceCrawlRuleResponse: ...


@dataclass(frozen=True)
class SupabaseSourceCrawlRuleRepository:
    """Supabase source_crawl_rules 테이블에 접근한다."""

    client: Client

    def create_candidate(
        self, rule: SourceCrawlRuleCreate
    ) -> SourceCrawlRuleResponse:
        """candidate 규칙을 저장하고 생성 결과를 반환한다."""
        payload = {
            "source_id": str(rule.source_id),
            "version": self._next_version(rule.source_id),
            "rule_schema_version": (
                2 if rule.detail_rule_definition is not None else 1
            ),
            "rule_definition": rule.rule_definition.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            ),
            "detail_rule_definition": (
                rule.detail_rule_definition.model_dump(
                    mode="json",
                    by_alias=True,
                    exclude_none=True,
                )
                if rule.detail_rule_definition is not None
                else None
            ),
            "list_crawl_mode": rule.list_crawl_mode.value,
            "detail_crawl_mode": rule.detail_crawl_mode.value,
            "generated_by": rule.generated_by.value,
        }

        # 삽입한 객체 전체 반환
        response = (
            self.client.table("source_crawl_rules")
            .insert(payload)
            .execute()
        )
        return self._parse_one(response.data)

    def get_active(
        self, source_id: UUID
    ) -> SourceCrawlRuleResponse | None:
        """Source의 active 규칙을 조회한다. 없으면 None을 반환한다."""
        response = (
            self.client.table("source_crawl_rules")
            .select("*")
            .eq("source_id", str(source_id))
            .eq("status", RuleStatus.ACTIVE.value)
            .limit(1)
            .execute()
        )
        rows = response.data
        if not rows:
            return None

        return self._parse_one(rows)

    def update_validation_status(
        self,
        rule_id: UUID,
        status: ValidationStatus,
    ) -> SourceCrawlRuleResponse:
        """규칙의 검증 상태를 변경한다."""
        validated_at = (
            None
            if status is ValidationStatus.PENDING
            else datetime.now(timezone.utc).isoformat()
        )
        return self._update(
            rule_id,
            {
                "validation_status": status.value,
                "validated_at": validated_at,
            },
        )

    def update_health_status(
        self,
        rule_id: UUID,
        status: HealthStatus,
    ) -> SourceCrawlRuleResponse:
        """active 규칙의 운영 상태를 변경한다."""
        rule = self._get_by_id(rule_id)
        if rule.status is not RuleStatus.ACTIVE:
            raise RuntimeError(
                "active가 아닌 규칙의 운영 상태는 변경할 수 없습니다."
            )

        return self._update(
            rule_id,
            {
                "health_status": status.value,
                "last_health_checked_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            },
        )

    def activate(self, rule_id: UUID) -> SourceCrawlRuleResponse:
        """검증을 통과한 규칙을 active로 바꾸고, 기존 active는 retired로 전환한다."""
        target = self._get_by_id(rule_id)
        if target.status is RuleStatus.ACTIVE:
            return target
        if target.validation_status is not ValidationStatus.PASSED:
            raise RuntimeError(
                "검증을 통과한 규칙만 활성화할 수 있습니다."
            )

        current = self.get_active(target.source_id)
        if current is not None:
            self._update(
                current.id,
                {
                    "status": RuleStatus.RETIRED.value,
                    "health_status": None,
                },
            )

        return self._update(
            target.id,
            {
                "status": RuleStatus.ACTIVE.value,
                "health_status": HealthStatus.UNKNOWN.value,
            },
        )

    def _next_version(self, source_id: UUID) -> int:
        """Source별 다음 version 번호를 계산한다."""
        response = (
            self.client.table("source_crawl_rules")
            .select("version")
            .eq("source_id", str(source_id))
            .order("version", desc=True)
            .limit(1)
            .execute()
        )
        rows = response.data
        if not rows:
            return 1

        row = rows[0]
        if not isinstance(row, Mapping):
            raise RuntimeError("크롤링 규칙 버전 데이터가 올바르지 않습니다.")

        version = row["version"]
        if not isinstance(version, int):
            raise RuntimeError("크롤링 규칙 버전이 올바르지 않습니다.")

        return version + 1

    def _get_by_id(self, rule_id: UUID) -> SourceCrawlRuleResponse:
        """id로 크롤링 규칙 한 행을 조회한다."""
        response = (
            self.client.table("source_crawl_rules")
            .select("*")
            .eq("id", str(rule_id))
            .limit(1)
            .execute()
        )
        return self._parse_one(response.data)

    def _update(
        self,
        rule_id: UUID,
        payload: dict[str, str | None],
    ) -> SourceCrawlRuleResponse:
        """지정한 규칙의 payload 컬럼만 갱신하고 갱신된 행을 반환한다."""
        response = (
            self.client.table("source_crawl_rules")
            .update(cast(JSON, payload))
            .eq("id", str(rule_id))
            .execute()
        )
        return self._parse_one(response.data)

    def _parse_one(self, rows: object) -> SourceCrawlRuleResponse:
        """Supabase 응답 한 행을 SourceCrawlRuleResponse로 변환한다."""
        if not isinstance(rows, list) or len(rows) != 1:
            raise RuntimeError("크롤링 규칙 저장 결과가 올바르지 않습니다.")

        row = rows[0]
        if not isinstance(row, Mapping):
            raise RuntimeError("크롤링 규칙 저장 데이터가 올바르지 않습니다.")

        return SourceCrawlRuleResponse.model_validate(row)
