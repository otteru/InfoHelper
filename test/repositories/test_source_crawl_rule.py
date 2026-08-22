"""SupabaseSourceCrawlRuleRepository의 candidate 생성 동작을 실제 DB 없이 검증한다."""

from datetime import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock
from uuid import UUID

import pytest
from supabase import Client

from app.repositories.crawl_rule import SupabaseSourceCrawlRuleRepository
from app.schemas.crawl_rule import (
    CrawlRuleDefinition,
    GeneratedBy,
    HealthStatus,
    RuleStatus,
    SourceCrawlRuleCreate,
    ValidationStatus,
)

SOURCE_ID = UUID("00000000-0000-0000-0000-000000000010")
RULE_ID = UUID("00000000-0000-0000-0000-000000000001")
OLD_RULE_ID = UUID("00000000-0000-0000-0000-000000000002")
CREATED_AT = "2026-08-22T00:00:00+09:00"
CHECKED_AT = "2026-08-22T01:00:00+09:00"

RULE_DEFINITION = {
    "name": "공지 목록",
    "baseSelector": "table tbody tr",
    "fields": [
        {
            "name": "title",
            "selector": "td.title a",
            "type": "text",
        },
        {
            "name": "url",
            "selector": "td.title a",
            "type": "attribute",
            "attribute": "href",
        },
    ],
}


def make_rule() -> SourceCrawlRuleCreate:
    """테스트용 candidate 생성 요청을 만든다."""
    return SourceCrawlRuleCreate(
        source_id=SOURCE_ID,
        rule_definition=CrawlRuleDefinition.model_validate(RULE_DEFINITION),
        generated_by=GeneratedBy.MANUAL,
    )


def saved_row(
    version: int,
    *,
    rule_id: UUID = RULE_ID,
    status: str = "candidate",
    validation_status: str = "pending",
    health_status: str | None = None,
    validated_at: str | None = None,
    last_health_checked_at: str | None = None,
) -> dict[str, object]:
    """Supabase가 반환한다고 가정한 규칙 행이다."""
    return {
        "id": str(rule_id),
        "source_id": str(SOURCE_ID),
        "version": version,
        "rule_schema_version": 1,
        "status": status,
        "validation_status": validation_status,
        "health_status": health_status,
        "rule_definition": RULE_DEFINITION,
        "generated_by": "manual",
        "created_at": CREATED_AT,
        "validated_at": validated_at,
        "last_health_checked_at": last_health_checked_at,
    }


def create_repository(
    *execute_data: object,
) -> tuple[SupabaseSourceCrawlRuleRepository, Mock, Mock]:
    """execute()가 순서대로 반환할 응답을 가진 Repository와 Mock을 만든다."""
    client = Mock(spec=Client)
    query = Mock()
    client.table.return_value = query

    query.select.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.insert.return_value = query
    query.update.return_value = query
    query.execute.side_effect = [
        SimpleNamespace(data=data) for data in execute_data
    ]

    repository = SupabaseSourceCrawlRuleRepository(
        client=cast(Client, client),
    )
    return repository, client, query


def expected_insert_payload(version: int) -> dict[str, object]:
    rule = make_rule()
    return {
        "source_id": str(rule.source_id),
        "version": version,
        "rule_definition": rule.rule_definition.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        ),
        "generated_by": rule.generated_by.value,
    }


def test_create_candidate_uses_version_one_when_no_rules_exist() -> None:
    """기존 규칙이 없으면 version 1로 candidate를 저장한다."""
    rule = make_rule()
    repository, client, query = create_repository(
        [],
        [saved_row(version=1)],
    )

    result = repository.create_candidate(rule)

    assert result.id == RULE_ID
    assert result.source_id == SOURCE_ID
    assert result.version == 1
    assert result.rule_schema_version == 1
    assert result.status is RuleStatus.CANDIDATE
    assert result.validation_status is ValidationStatus.PENDING
    assert result.health_status is None
    assert result.generated_by is GeneratedBy.MANUAL
    assert result.created_at == datetime.fromisoformat(CREATED_AT)
    assert result.validated_at is None
    assert result.last_health_checked_at is None
    assert result.rule_definition.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    ) == RULE_DEFINITION

    assert client.table.call_count == 2
    client.table.assert_called_with("source_crawl_rules")
    query.select.assert_called_once_with("version")
    query.eq.assert_called_once_with("source_id", str(SOURCE_ID))
    query.order.assert_called_once_with("version", desc=True)
    query.limit.assert_called_once_with(1)
    query.insert.assert_called_once_with(expected_insert_payload(version=1))
    assert query.execute.call_count == 2


def test_create_candidate_increments_existing_version() -> None:
    """기존 최대 version이 있으면 그 다음 번호로 저장한다."""
    rule = make_rule()
    repository, _, query = create_repository(
        [{"version": 1}],
        [saved_row(version=2)],
    )

    result = repository.create_candidate(rule)

    assert result.version == 2
    query.insert.assert_called_once_with(expected_insert_payload(version=2))


@pytest.mark.parametrize(
    "insert_rows",
    [
        pytest.param(None, id="none"),
        pytest.param({}, id="mapping"),
        pytest.param([], id="empty-list"),
        pytest.param([{}, {}], id="multiple-rows"),
    ],
)
def test_create_candidate_rejects_invalid_insert_response(
    insert_rows: object,
) -> None:
    """INSERT 응답이 단 하나의 행을 가진 리스트가 아니면 거부한다."""
    repository, _, _ = create_repository([], insert_rows)

    with pytest.raises(
        RuntimeError,
        match="크롤링 규칙 저장 결과가 올바르지 않습니다",
    ):
        repository.create_candidate(make_rule())


def test_create_candidate_rejects_invalid_insert_row() -> None:
    """INSERT 응답의 행이 객체 형식이 아니면 거부한다."""
    repository, _, _ = create_repository([], ["잘못된 데이터"])

    with pytest.raises(
        RuntimeError,
        match="크롤링 규칙 저장 데이터가 올바르지 않습니다",
    ):
        repository.create_candidate(make_rule())


def test_create_candidate_rejects_invalid_version_row() -> None:
    """version 조회 행이 객체가 아니면 거부한다."""
    repository, _, query = create_repository(
        ["잘못된 데이터"],
        [saved_row(version=1)],
    )

    with pytest.raises(
        RuntimeError,
        match="크롤링 규칙 버전 데이터가 올바르지 않습니다",
    ):
        repository.create_candidate(make_rule())

    query.insert.assert_not_called()


def test_create_candidate_rejects_non_integer_version() -> None:
    """version 값이 정수가 아니면 거부한다."""
    repository, _, query = create_repository(
        [{"version": "1"}],
        [saved_row(version=2)],
    )

    with pytest.raises(
        RuntimeError,
        match="크롤링 규칙 버전이 올바르지 않습니다",
    ):
        repository.create_candidate(make_rule())

    query.insert.assert_not_called()


def test_get_active_returns_active_rule() -> None:
    """Source의 active 규칙을 조회한다."""
    active = saved_row(
        version=1,
        status="active",
        health_status="unknown",
    )
    repository, _, query = create_repository([active])

    result = repository.get_active(SOURCE_ID)

    assert result is not None
    assert result.id == RULE_ID
    assert result.status is RuleStatus.ACTIVE
    assert result.health_status is HealthStatus.UNKNOWN
    query.select.assert_called_once_with("*")
    query.eq.assert_any_call("source_id", str(SOURCE_ID))
    query.eq.assert_any_call("status", RuleStatus.ACTIVE.value)


def test_get_active_returns_none_when_missing() -> None:
    """active 규칙이 없으면 None을 반환한다."""
    repository, _, query = create_repository([])

    result = repository.get_active(SOURCE_ID)

    assert result is None
    query.update.assert_not_called()


def test_update_validation_status_sets_validated_at() -> None:
    """검증 통과 시 validation_status와 validated_at을 갱신한다."""
    updated = saved_row(
        version=1,
        validation_status="passed",
        validated_at=CHECKED_AT,
    )
    repository, _, query = create_repository([updated])

    result = repository.update_validation_status(
        RULE_ID,
        ValidationStatus.PASSED,
    )

    assert result.validation_status is ValidationStatus.PASSED
    payload = query.update.call_args.args[0]
    assert payload["validation_status"] == "passed"
    assert payload["validated_at"] is not None
    query.eq.assert_called_once_with("id", str(RULE_ID))


def test_update_validation_status_clears_validated_at_when_pending() -> None:
    """검증 상태를 pending으로 되돌리면 validated_at을 비운다."""
    updated = saved_row(version=1)
    repository, _, query = create_repository([updated])

    repository.update_validation_status(RULE_ID, ValidationStatus.PENDING)

    payload = query.update.call_args.args[0]
    assert payload == {
        "validation_status": "pending",
        "validated_at": None,
    }


def test_update_health_status_updates_active_rule() -> None:
    """active 규칙의 운영 상태를 변경한다."""
    active = saved_row(
        version=1,
        status="active",
        health_status="unknown",
    )
    updated = saved_row(
        version=1,
        status="active",
        health_status="healthy",
        last_health_checked_at=CHECKED_AT,
    )
    repository, _, query = create_repository([active], [updated])

    result = repository.update_health_status(
        RULE_ID,
        HealthStatus.HEALTHY,
    )

    assert result.health_status is HealthStatus.HEALTHY
    payload = query.update.call_args.args[0]
    assert payload["health_status"] == "healthy"
    assert payload["last_health_checked_at"] is not None


def test_update_health_status_rejects_inactive_rule() -> None:
    """candidate 규칙의 운영 상태는 변경하지 않는다."""
    candidate = saved_row(version=1)
    repository, _, query = create_repository([candidate])

    with pytest.raises(
        RuntimeError,
        match="active가 아닌 규칙의 운영 상태는 변경할 수 없습니다",
    ):
        repository.update_health_status(RULE_ID, HealthStatus.HEALTHY)

    query.update.assert_not_called()


def test_activate_promotes_candidate_when_no_active_exists() -> None:
    """기존 active가 없으면 candidate를 active로 바꾼다."""
    candidate = saved_row(version=1)
    activated = saved_row(
        version=1,
        status="active",
        health_status="unknown",
    )
    repository, _, query = create_repository(
        [candidate],
        [],
        [activated],
    )

    result = repository.activate(RULE_ID)

    assert result.status is RuleStatus.ACTIVE
    assert result.health_status is HealthStatus.UNKNOWN
    query.update.assert_called_once_with(
        {
            "status": "active",
            "health_status": "unknown",
        }
    )


def test_activate_retires_existing_active_rule() -> None:
    """기존 active 규칙을 retired로 바꾼 뒤 새 규칙을 활성화한다."""
    candidate = saved_row(version=2)
    current_active = saved_row(
        version=1,
        rule_id=OLD_RULE_ID,
        status="active",
        health_status="healthy",
    )
    retired = saved_row(
        version=1,
        rule_id=OLD_RULE_ID,
        status="retired",
    )
    activated = saved_row(
        version=2,
        status="active",
        health_status="unknown",
    )
    repository, _, query = create_repository(
        [candidate],
        [current_active],
        [retired],
        [activated],
    )

    result = repository.activate(RULE_ID)

    assert result.id == RULE_ID
    assert result.status is RuleStatus.ACTIVE
    assert query.update.call_args_list[0].args[0] == {
        "status": "retired",
        "health_status": None,
    }
    assert query.update.call_args_list[1].args[0] == {
        "status": "active",
        "health_status": "unknown",
    }
    assert query.eq.call_args_list[-2].args == ("id", str(OLD_RULE_ID))
    assert query.eq.call_args_list[-1].args == ("id", str(RULE_ID))


def test_activate_returns_existing_active_rule() -> None:
    """이미 active인 규칙은 그대로 반환한다."""
    active = saved_row(
        version=1,
        status="active",
        health_status="healthy",
    )
    repository, _, query = create_repository([active])

    result = repository.activate(RULE_ID)

    assert result.status is RuleStatus.ACTIVE
    assert result.health_status is HealthStatus.HEALTHY
    query.update.assert_not_called()

