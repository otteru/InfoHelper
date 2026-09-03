import pytest
from pydantic import ValidationError

from app.schemas.crawl_rule import (
    CrawlMode,
    CrawlRuleDefinition,
    CrawlRuleField,
    CrawlRuleGenerationRequest,
)


def test_크롤링_모드는_허용된값만_가진다() -> None:
    """수집 모드 문자열을 CrawlMode로 검증한다."""
    assert CrawlMode("dynamic") is CrawlMode.DYNAMIC

    with pytest.raises(ValueError):
        CrawlMode("javascript")


def test_규칙_생성_요청은_목록과_상세_모드를_분리한다() -> None:
    """목록과 상세 페이지의 수집 모드를 각각 받는다."""
    request = CrawlRuleGenerationRequest.model_validate(
        {
            "list_crawl_mode": "infinite_scroll",
            "detail_crawl_mode": "dynamic",
        }
    )

    assert request.list_crawl_mode is CrawlMode.INFINITE_SCROLL
    assert request.detail_crawl_mode is CrawlMode.DYNAMIC


def test_css_크롤링_규칙을_crawl4ai_형식으로_변환한다() -> None:
    rule = CrawlRuleDefinition.model_validate(
        {
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
    )

    assert rule.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    ) == {
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


def test_attribute_추출에는_속성명이_필요하다() -> None:
    with pytest.raises(
        ValidationError,
        match="attribute 타입에는 attribute가 필요합니다.",
    ):
        CrawlRuleField(
            name="url",
            selector="td.title a",
            type="attribute",
        )


def test_base_fields를_Crawl4AI_형식으로_변환한다() -> None:
    """목록 항목 루트의 속성 추출 규칙을 보존한다."""
    rule = CrawlRuleDefinition.model_validate(
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

    assert rule.model_dump(mode="json", by_alias=True) == {
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
                "attribute": None,
            }
        ],
    }


def test_크롤링_규칙에는_하나_이상의_필드가_필요하다() -> None:
    with pytest.raises(ValidationError):
        CrawlRuleDefinition.model_validate(
            {
                "name": "공지 목록",
                "baseSelector": "table tbody tr",
                "fields": [],
            }
        )


def test_건국대_생성_스키마를_모델로_검증한다() -> None:
    """로컬 generate_schema로 확인한 건국대 CSS 규칙을 모델이 받는지 검증한다."""
    schema = {
        "name": "Notice Board Items",
        "baseSelector": "table.board-table tbody tr",
        "fields": [
            {
                "name": "title",
                "selector": "td.td-subject strong",
                "type": "text",
            },
            {
                "name": "url",
                "selector": "td.td-subject a",
                "type": "attribute",
                "attribute": "href",
            },
        ],
    }

    rule = CrawlRuleDefinition.model_validate(schema)

    assert rule.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    ) == schema
