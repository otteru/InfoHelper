"""CSS 크롤링 규칙 검증과 상태 전환을 검증한다."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, call, patch
from uuid import UUID

import pytest

from app.exceptions import CrawlRuleGenerationError, CrawlRuleValidationError
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
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

from app.services.crawl_rule import (
    NoticeRuleSample,
    _normalize_root_link_url,
    fetch_html,
    generate_candidate,
    generate_css_schema,
    validate_detail_css_rule,
    validate_css_rule,
)
from integrations.url_safety import UnsafeUrlError

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

DETAIL_RULE_DEFINITION = CrawlRuleDefinition.model_validate(
    {
        "name": "공지 상세",
        "baseSelector": "article",
        "fields": [
            {
                "name": "title",
                "selector": "h1",
                "type": "text",
            },
            {
                "name": "content",
                "selector": ".content",
                "type": "text",
            },
        ],
    }
)

SAMPLES = tuple(
    NoticeRuleSample(
        title=f"공지 {index}",
        url=f"https://example.com/notices/{index}",
    )
    for index in range(1, 5)
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
    *,
    detail_rule_definition: CrawlRuleDefinition | None = None,
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
        detail_rule_definition=detail_rule_definition,
    )


def test_fetch_html_rejects_unsafe_url_before_browser() -> None:
    """안전하지 않은 URL은 브라우저를 실행하기 전에 거부한다."""
    with (
        patch(
            "app.services.crawl_rule.validate_public_url",
            side_effect=UnsafeUrlError("공개 IP가 아닙니다."),
        ),
        patch("app.services.crawl_rule.AsyncWebCrawler") as crawler,
        pytest.raises(
            CrawlRuleGenerationError,
            match="안전하지 않은 URL",
        ),
    ):
        asyncio.run(fetch_html("https://127.0.0.1/admin"))

    crawler.assert_not_called()


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
        result = validate_css_rule(SOURCE_URL, HTML, RULE_DEFINITION)

    strategy.extract.assert_called_once_with(SOURCE_URL, HTML)
    assert result == (
        NoticeRuleSample(
            title="장학금 공지",
            url="https://example.com/notices/1",
        ),
    )


def test_validate_css_rule_accepts_url_in_base_fields() -> None:
    """목록 항목 자체의 href를 url 필드로 검증한다."""
    definition = CrawlRuleDefinition.model_validate(
        {
            "name": "채용 공고 목록",
            "baseSelector": "a.relative",
            "baseFields": [
                {
                    "name": "url",
                    "type": "attribute",
                    "attribute": "href",
                }
            ],
            "fields": [
                {
                    "name": "title",
                    "selector": "span.title",
                    "type": "text",
                }
            ],
        }
    )
    strategy = Mock()
    strategy.extract.return_value = [
        {"title": "백엔드 개발자", "url": "/recruitment/1"}
    ]

    with patch(
        "app.services.crawl_rule.JsonCssExtractionStrategy",
        return_value=strategy,
    ):
        result = validate_css_rule(SOURCE_URL, HTML, definition)

    assert result[0].url == "https://example.com/recruitment/1"


ROOT_ANCHOR_RULE = CrawlRuleDefinition.model_validate(
    {
        "name": "Job Listings",
        "baseSelector": "a[class^='relative']",
        "fields": [
            {
                "name": "title",
                "selector": ".typo-body-lg-semi-bold",
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


def test_루트가_a이면_자식_a_url을_baseFields로_옮긴다() -> None:
    """카드 루트가 a인데 url이 자식 a를 찾으면 루트 href로 보정한다."""
    result = _normalize_root_link_url(ROOT_ANCHOR_RULE)

    assert result.base_selector == "a[class^='relative']"
    assert [field.name for field in result.fields] == ["title"]
    assert result.base_fields is not None
    assert result.base_fields[0].name == "url"
    assert result.base_fields[0].type == "attribute"
    assert result.base_fields[0].attribute == "href"


def test_루트가_div이면_자식_a_url을_유지한다() -> None:
    """항목 루트가 링크가 아니면 자식 a href 규칙을 건드리지 않는다."""
    rule = CrawlRuleDefinition.model_validate(
        {
            "name": "공지 목록",
            "baseSelector": "div.card",
            "fields": [
                {
                    "name": "title",
                    "selector": "span.title",
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

    assert _normalize_root_link_url(rule) == rule


def test_보정된_루트_a_규칙으로_title과_url을_추출한다() -> None:
    """보정 후 실제 CSS 추출에서 href가 채워지는지 확인한다."""
    html = (
        '<a class="relative" href="/recruitment/abc">'
        '<span class="typo-body-lg-semi-bold">백엔드 리드</span>'
        "</a>"
    )
    normalized = _normalize_root_link_url(ROOT_ANCHOR_RULE)
    schema = normalized.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )
    items = JsonCssExtractionStrategy(schema).extract(SOURCE_URL, html)

    assert items == [
        {
            "title": "백엔드 리드",
            "url": "/recruitment/abc",
        }
    ]


def test_generate_css_schema가_루트_a_url을_보정한다() -> None:
    """목록 스키마 생성 결과에 루트 링크 보정을 적용한다."""
    async def fake_generate(*args: object, **kwargs: object) -> CrawlRuleDefinition:
        return ROOT_ANCHOR_RULE

    with patch(
        "app.services.crawl_rule._generate_css_schema",
        side_effect=fake_generate,
    ):
        result = asyncio.run(generate_css_schema("<html></html>"))

    assert result.base_fields is not None
    assert result.base_fields[0].name == "url"
    assert [field.name for field in result.fields] == ["title"]


def test_validate_detail_css_rule_uses_list_title_as_fallback() -> None:
    """상세 제목이 비어 있으면 목록에서 추출한 제목을 사용한다."""
    strategy = Mock()
    strategy.extract.return_value = [
        {"title": "", "content": "실제 공지 본문"}
    ]

    with patch(
        "app.services.crawl_rule.JsonCssExtractionStrategy",
        return_value=strategy,
    ):
        result = validate_detail_css_rule(
            "https://example.com/notices/1",
            "<article></article>",
            DETAIL_RULE_DEFINITION,
            "목록 공지 제목",
        )

    assert result == ("목록 공지 제목", "실제 공지 본문")


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
        detail_rule_definition=DETAIL_RULE_DEFINITION,
    )
    active = make_rule_response(
        RuleStatus.ACTIVE,
        ValidationStatus.PASSED,
        detail_rule_definition=DETAIL_RULE_DEFINITION,
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
            new=AsyncMock(
                side_effect=[HTML, "상세1", "상세2", "상세3"]
            ),
        ),
        patch(
            "app.services.crawl_rule.generate_css_schema",
            new=AsyncMock(return_value=RULE_DEFINITION),
        ),
        patch(
            "app.services.crawl_rule.generate_detail_css_schema",
            new=AsyncMock(return_value=DETAIL_RULE_DEFINITION),
        ),
        patch(
            "app.services.crawl_rule.validate_css_rule",
            return_value=SAMPLES,
        ) as validate_list,
        patch(
            "app.services.crawl_rule.validate_detail_css_rule"
        ) as validate_detail,
    ):
        result = asyncio.run(generate_candidate(make_source(), repository))

    assert result == active
    validate_list.assert_called_once_with(SOURCE_URL, HTML, RULE_DEFINITION)
    assert validate_detail.call_args_list == [
        call(sample.url, detail_html, DETAIL_RULE_DEFINITION, sample.title)
        for sample, detail_html in zip(
            SAMPLES,
            ("상세1", "상세2", "상세3"),
            strict=False,
        )
    ]
    created_rule = repository.create_candidate.call_args.args[0]
    assert created_rule.detail_rule_definition == DETAIL_RULE_DEFINITION
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
        detail_rule_definition=DETAIL_RULE_DEFINITION,
    )
    repository.create_candidate.return_value = candidate
    repository.update_validation_status.return_value = make_rule_response(
        RuleStatus.CANDIDATE,
        ValidationStatus.FAILED,
    )

    with (
        patch(
            "app.services.crawl_rule.fetch_html",
            new=AsyncMock(
                side_effect=[HTML, "상세1", "상세2", "상세3"]
            ),
        ),
        patch(
            "app.services.crawl_rule.generate_css_schema",
            new=AsyncMock(return_value=RULE_DEFINITION),
        ),
        patch(
            "app.services.crawl_rule.validate_css_rule",
            return_value=SAMPLES,
        ),
        patch(
            "app.services.crawl_rule.generate_detail_css_schema",
            new=AsyncMock(return_value=DETAIL_RULE_DEFINITION),
        ),
        patch(
            "app.services.crawl_rule.validate_detail_css_rule",
            side_effect=CrawlRuleValidationError("검증 실패"),
        ),
        pytest.raises(CrawlRuleValidationError, match="충분한 샘플"),
    ):
        asyncio.run(generate_candidate(make_source(), repository))

    repository.update_validation_status.assert_called_once_with(
        RULE_ID,
        ValidationStatus.FAILED,
    )
    repository.activate.assert_not_called()


def test_generate_candidate_accepts_two_of_three_detail_samples() -> None:
    """상세 샘플 세 개 중 두 개가 성공하면 규칙을 활성화한다."""
    repository = Mock(spec=SourceCrawlRuleRepository)
    candidate = make_rule_response(
        RuleStatus.CANDIDATE,
        ValidationStatus.PENDING,
        detail_rule_definition=DETAIL_RULE_DEFINITION,
    )
    active = make_rule_response(
        RuleStatus.ACTIVE,
        ValidationStatus.PASSED,
        detail_rule_definition=DETAIL_RULE_DEFINITION,
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
            new=AsyncMock(
                side_effect=[HTML, "상세1", "상세2", "상세3"]
            ),
        ),
        patch(
            "app.services.crawl_rule.generate_css_schema",
            new=AsyncMock(return_value=RULE_DEFINITION),
        ),
        patch(
            "app.services.crawl_rule.validate_css_rule",
            return_value=SAMPLES,
        ),
        patch(
            "app.services.crawl_rule.generate_detail_css_schema",
            new=AsyncMock(return_value=DETAIL_RULE_DEFINITION),
        ),
        patch(
            "app.services.crawl_rule.validate_detail_css_rule",
            side_effect=[
                None,
                CrawlRuleValidationError("본문 없음"),
                None,
            ],
        ),
    ):
        result = asyncio.run(generate_candidate(make_source(), repository))

    assert result == active
    repository.update_validation_status.assert_called_once_with(
        RULE_ID,
        ValidationStatus.PASSED,
    )
    repository.activate.assert_called_once_with(RULE_ID)
