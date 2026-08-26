"""CSS 크롤링 규칙 검증과 상태 전환을 검증한다."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, call, patch
from uuid import UUID

import pytest

from app.exceptions import CrawlRuleValidationError
from app.repositories.crawl_rule import SourceCrawlRuleRepository
from app.schemas.crawl_rule import (
    CrawlRuleDefinition,
    GeneratedBy,
    HealthStatus,
    RuleStatus,
    SourceCrawlRuleResponse,
    ValidationStatus,
)
from app.schemas.source import SourceResponse
from app.services.crawl_rule import (
    generate_candidate,
    validate_css_rule,
)

SOURCE_ID = UUID("00000000-0000-0000-0000-000000000010")
RULE_ID = UUID("00000000-0000-0000-0000-000000000001")
SOURCE_URL = "https://example.com/notices"
HTML = "<table><tr><td><a href='/notices/1'>공지</a></td></tr></table>"

RULE_DEFINITION = CrawlRuleDefinition.model_validate(
    {
        "name": "공지 목록",
        "baseSelector": "table tr",
        "fields": [
            {
                "name": "title",
                "selector": "a",
                "type": "text",
            },
            {
                "name": "url",
                "selector": "a",
                "type": "attribute",
                "attribute": "href",
            },
        ],
    }
)


def make_source() -> SourceResponse:
    """테스트용 Source 응답을 만든다."""
    return SourceResponse(
        id=SOURCE_ID,
        name="테스트 공지",
        url=SOURCE_URL,
        created_at=datetime.fromisoformat("2026-08-26T00:00:00+09:00"),
    )


def make_rule_response(
    status: RuleStatus,
    validation_status: ValidationStatus,
) -> SourceCrawlRuleResponse:
    """테스트용 크롤링 규칙 응답을 만든다."""
    return SourceCrawlRuleResponse(
        id=RULE_ID,
        source_id=SOURCE_ID,
        version=1,
        rule_schema_version=1,
        status=status,
        validation_status=validation_status,
        health_status=(
            HealthStatus.UNKNOWN if status is RuleStatus.ACTIVE else None
        ),
        rule_definition=RULE_DEFINITION,
        generated_by=GeneratedBy.LLM,
        created_at=datetime.fromisoformat("2026-08-26T00:00:00+09:00"),
        validated_at=None,
        last_health_checked_at=None,
    )


def test_validate_css_rule_accepts_complete_extraction() -> None:
    """title과 url이 채워진 추출 결과를 통과시킨다."""
    strategy = Mock()
    strategy.extract.return_value = [
        {"title": "장학금 공지", "url": "/notices/1"}
    ]

    with patch(
        "app.services.crawl_rule.JsonCssExtractionStrategy",
        return_value=strategy,
    ):
        validate_css_rule(SOURCE_URL, HTML, RULE_DEFINITION)

    strategy.extract.assert_called_once_with(SOURCE_URL, HTML)


def test_validate_css_rule_rejects_missing_required_field() -> None:
    """스키마에 title 또는 url 필드가 없으면 검증에 실패한다."""
    definition = CrawlRuleDefinition.model_validate(
        {
            "name": "공지 목록",
            "baseSelector": "table tr",
            "fields": [
                {
                    "name": "title",
                    "selector": "a",
                    "type": "text",
                }
            ],
        }
    )

    with pytest.raises(
        CrawlRuleValidationError,
        match="title과 url 필드가 필요합니다",
    ):
        validate_css_rule(SOURCE_URL, HTML, definition)


@pytest.mark.parametrize(
    "items",
    [
        pytest.param(None, id="none"),
        pytest.param([], id="empty"),
        pytest.param(
            [{"title": "", "url": "/notices/1"}],
            id="empty-title",
        ),
        pytest.param(
            [{"title": "장학금 공지", "url": ""}],
            id="empty-url",
        ),
    ],
)
def test_validate_css_rule_rejects_incomplete_extraction(
    items: object,
) -> None:
    """완전한 title과 url 추출 결과가 없으면 검증에 실패한다."""
    strategy = Mock()
    strategy.extract.return_value = items

    with (
        patch(
            "app.services.crawl_rule.JsonCssExtractionStrategy",
            return_value=strategy,
        ),
        pytest.raises(
            CrawlRuleValidationError,
            match="유효한 공지를 추출하지 못했습니다",
        ),
    ):
        validate_css_rule(SOURCE_URL, HTML, RULE_DEFINITION)


def test_generate_candidate_marks_passed_and_activates_rule() -> None:
    """검증 성공 시 candidate를 passed와 active로 전환한다."""
    repository = Mock(spec=SourceCrawlRuleRepository)
    candidate = make_rule_response(
        RuleStatus.CANDIDATE,
        ValidationStatus.PENDING,
    )
    active = make_rule_response(
        RuleStatus.ACTIVE,
        ValidationStatus.PASSED,
    )
    repository.create_candidate.return_value = candidate
    repository.update_validation_status.return_value = make_rule_response(
        RuleStatus.CANDIDATE,
        ValidationStatus.PASSED,
    )
    repository.activate.return_value = active

    with (
        patch(
            "app.services.crawl_rule.fetch_html",
            new=AsyncMock(return_value=HTML),
        ),
        patch(
            "app.services.crawl_rule.generate_css_schema",
            return_value=RULE_DEFINITION,
        ),
        patch("app.services.crawl_rule.validate_css_rule") as validate,
    ):
        result = asyncio.run(generate_candidate(make_source(), repository))

    assert result == active
    validate.assert_called_once_with(SOURCE_URL, HTML, RULE_DEFINITION)
    assert repository.method_calls == [
        call.create_candidate(repository.create_candidate.call_args.args[0]),
        call.update_validation_status(RULE_ID, ValidationStatus.PASSED),
        call.activate(RULE_ID),
    ]


def test_generate_candidate_marks_failed_without_activation() -> None:
    """검증 실패 시 candidate를 failed로 바꾸고 활성화하지 않는다."""
    repository = Mock(spec=SourceCrawlRuleRepository)
    candidate = make_rule_response(
        RuleStatus.CANDIDATE,
        ValidationStatus.PENDING,
    )
    repository.create_candidate.return_value = candidate
    repository.update_validation_status.return_value = make_rule_response(
        RuleStatus.CANDIDATE,
        ValidationStatus.FAILED,
    )

    with (
        patch(
            "app.services.crawl_rule.fetch_html",
            new=AsyncMock(return_value=HTML),
        ),
        patch(
            "app.services.crawl_rule.generate_css_schema",
            return_value=RULE_DEFINITION,
        ),
        patch(
            "app.services.crawl_rule.validate_css_rule",
            side_effect=CrawlRuleValidationError("검증 실패"),
        ),
        pytest.raises(CrawlRuleValidationError, match="검증 실패"),
    ):
        asyncio.run(generate_candidate(make_source(), repository))

    repository.update_validation_status.assert_called_once_with(
        RULE_ID,
        ValidationStatus.FAILED,
    )
    repository.activate.assert_not_called()
