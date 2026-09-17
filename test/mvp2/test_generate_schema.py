"""건국대 공지 페이지에서 Crawl4AI generate_schema가 CSS 규칙을 만드는지 확인한다."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CacheMode,
    CrawlerRunConfig,
    LLMConfig,
)
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas.crawl_rule import CrawlRuleDefinition
from app.services.crawl_rule import (
    DETAIL_SAMPLE_COUNT,
    LIST_SCHEMA_QUERY,
    MINIMUM_DETAIL_SAMPLE_SUCCESSES,
    NoticeRuleSample,
    fetch_html as fetch_service_html,
    generate_css_schema as generate_list_css_schema,
    generate_detail_css_schema,
    validate_css_rule,
    validate_detail_css_rule,
)
from integrations.clients import (
    CRAWL4AI_GENERATION_PROVIDER,
    OPENROUTER_BASE_URL,
)

load_dotenv(PROJECT_ROOT / ".env.local")
load_dotenv(PROJECT_ROOT / ".env")

KONKUK_NOTICE_URL = "https://www.konkuk.ac.kr/bbs/ee/407/artclList.do"
SCHEMA_QUERY = LIST_SCHEMA_QUERY
SCHEMA_EXAMPLE = json.dumps(
    {
        "title": "2026학년도 2학기 현장실습학기제 안내",
        "url": "https://www.konkuk.ac.kr/bbs/ee/407/1200817/artclView.do",
    },
    ensure_ascii=False,
)


def get_openrouter_api_token() -> str:
    """Crawl4AI LLM 호출에 사용할 OpenRouter API 키를 반환한다."""
    token = os.environ.get("OPENROUTER_API_KEY")
    if not token:
        raise RuntimeError("OPENROUTER_API_KEY가 필요합니다.")
    return token


async def fetch_html(url: str) -> str:
    """Crawl4AI로 페이지 HTML을 가져온다."""
    browser_config = BrowserConfig(headless=True, verbose=False)
    crawler_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=crawler_config)

    if not result.success or not result.html:
        raise RuntimeError(f"페이지 크롤링 실패: {result.error_message}")

    return result.cleaned_html or result.html


def generate_css_schema(html: str) -> dict[str, object]:
    """HTML에서 Crawl4AI LLM으로 CSS 추출 스키마를 생성한다."""
    schema = JsonCssExtractionStrategy.generate_schema(
        html=html,
        schema_type="CSS",
        query=SCHEMA_QUERY,
        target_json_example=SCHEMA_EXAMPLE,
        llm_config=LLMConfig(
            provider=CRAWL4AI_GENERATION_PROVIDER,
            api_token=get_openrouter_api_token(),
            base_url=OPENROUTER_BASE_URL,
        ),
        validate=False,
    )
    if not isinstance(schema, dict):
        raise RuntimeError("generate_schema 결과가 객체가 아닙니다.")
    return schema


def extract_notices(
    url: str,
    html: str,
    schema: dict[str, object],
) -> list[dict[str, object]]:
    """생성된 CSS 스키마로 공지 목록을 추출한다."""
    strategy = JsonCssExtractionStrategy(schema)
    items = strategy.extract(url, html)
    return [item for item in items if isinstance(item, dict)]


def print_report(
    schema: dict[str, object],
    items: list[dict[str, object]],
) -> None:
    """생성 스키마와 추출 샘플을 출력한다."""
    print("\n=== generated schema ===")
    print(json.dumps(schema, ensure_ascii=False, indent=2))
    print(f"\n=== extracted {len(items)} items ===")
    print(json.dumps(items[:5], ensure_ascii=False, indent=2))


async def run_konkuk_schema_generation() -> tuple[
    dict[str, object],
    list[dict[str, object]],
]:
    """건국대 공지 페이지의 CSS 스키마 생성과 샘플 추출을 실행한다."""
    html = await fetch_html(KONKUK_NOTICE_URL)
    schema = generate_css_schema(html)
    items = extract_notices(KONKUK_NOTICE_URL, html, schema)
    print_report(schema, items)
    return schema, items


async def run_konkuk_detail_rule_e2e() -> tuple[
    CrawlRuleDefinition,
    CrawlRuleDefinition,
    tuple[NoticeRuleSample, ...],
    int,
]:
    """건국대 실제 페이지에서 상세 규칙 생성과 추출을 검증한다."""
    list_html = await fetch_service_html(KONKUK_NOTICE_URL)
    list_rule = await asyncio.to_thread(
        generate_list_css_schema,
        list_html,
    )
    samples = validate_css_rule(
        KONKUK_NOTICE_URL,
        list_html,
        list_rule,
    )[:DETAIL_SAMPLE_COUNT]
    detail_pages: tuple[tuple[NoticeRuleSample, str], ...] = ()
    for sample in samples:
        detail_pages = (
            *detail_pages,
            (sample, await fetch_service_html(sample.url)),
        )
    if not detail_pages:
        raise RuntimeError("상세 규칙을 생성할 공지 샘플이 없습니다.")

    detail_rule = await asyncio.to_thread(
        generate_detail_css_schema,
        detail_pages[0][1],
    )
    successful_extractions = 0
    for sample, detail_html in detail_pages:
        try:
            validate_detail_css_rule(
                sample.url,
                detail_html,
                detail_rule,
                sample.title,
            )
        except Exception as error:
            print(f"상세 추출 실패: {sample.url} ({error})")
            continue
        successful_extractions += 1

    print("\n=== detail schema ===")
    print(json.dumps(detail_rule.model_dump(by_alias=True), ensure_ascii=False))
    print(
        "상세 추출 성공: "
        f"{successful_extractions}/{len(detail_pages)}"
    )
    return list_rule, detail_rule, samples, successful_extractions


@pytest.mark.skipif(
    os.environ.get("RUN_GENERATE_SCHEMA_TEST") != "1",
    reason="네트워크와 LLM을 사용하므로 기본 pytest에서 제외한다.",
)
def test_건국대_공지_css_스키마를_생성한다() -> None:
    """generate_schema가 건국대 공지 title/url 규칙을 만드는지 검증한다."""
    schema, items = asyncio.run(run_konkuk_schema_generation())

    rule = CrawlRuleDefinition.model_validate(schema)
    field_names = {field.name for field in rule.fields}
    assert "title" in field_names
    assert "url" in field_names
    assert len(items) >= 1
    assert items[0].get("title")
    assert items[0].get("url")


@pytest.mark.skipif(
    os.environ.get("RUN_DETAIL_SCHEMA_E2E") != "1",
    reason="네트워크와 LLM을 사용하므로 기본 pytest에서 제외한다.",
)
def test_건국대_상세_css_규칙을_생성하고_추출한다() -> None:
    """실제 상세 공지에서 생성한 CSS 규칙의 추출 성공률을 검증한다."""
    list_rule, detail_rule, samples, successful_extractions = asyncio.run(
        run_konkuk_detail_rule_e2e()
    )

    assert {field.name for field in list_rule.fields} >= {"title", "url"}
    assert {field.name for field in detail_rule.fields} >= {
        "title",
        "content",
    }
    assert successful_extractions >= min(
        MINIMUM_DETAIL_SAMPLE_SUCCESSES,
        len(samples),
    )


if __name__ == "__main__":
    schema, items = asyncio.run(run_konkuk_schema_generation())
    CrawlRuleDefinition.model_validate(schema)
    if not items:
        raise SystemExit("추출된 공지가 없습니다.")
