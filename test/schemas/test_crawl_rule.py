import pytest
from pydantic import ValidationError

from app.schemas.crawl_rule import CrawlRuleDefinition, CrawlRuleField


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


def test_크롤링_규칙에는_하나_이상의_필드가_필요하다() -> None:
    with pytest.raises(ValidationError):
        CrawlRuleDefinition.model_validate(
            {
                "name": "공지 목록",
                "baseSelector": "table tbody tr",
                "fields": [],
            }
        )
