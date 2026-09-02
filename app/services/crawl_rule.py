import asyncio
import json
import os
from dataclasses import dataclass
from urllib.parse import urljoin

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CacheMode,
    CrawlerRunConfig,
    LLMConfig,
)
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
from pydantic import ValidationError

from app.exceptions import CrawlRuleGenerationError, CrawlRuleValidationError
from app.repositories.crawl_rule import SourceCrawlRuleRepository
from app.schemas.crawl_rule import (
    CrawlRuleDefinition,
    GeneratedBy,
    SourceCrawlRuleCreate,
    SourceCrawlRuleResponse,
    ValidationStatus,
)
from app.schemas.source import SourceResponse
from integrations.url_safety import UnsafeUrlError, validate_public_url

GEMINI_FLASH_PROVIDER = "gemini/gemini-2.5-flash"
LIST_SCHEMA_QUERY = (
    "공지 목록의 각 행에서 제목(title)과 상세 페이지 링크(url)를 추출한다."
)
LIST_SCHEMA_EXAMPLE = json.dumps(
    {
        "title": "공지 제목",
        "url": "https://example.com/notice/1",
    },
    ensure_ascii=False,
)
DETAIL_SCHEMA_QUERY = (
    "공지 상세 페이지에서 실제 공지 제목(title)과 본문(content)만 추출한다. "
    "사이트 메뉴, 푸터, 이전 글, 다음 글, 관련 공지 목록은 제외한다."
)
DETAIL_SCHEMA_EXAMPLE = json.dumps(
    {
        "title": "공지 제목",
        "content": "공지의 실제 본문 내용",
    },
    ensure_ascii=False,
)
DETAIL_SAMPLE_COUNT = 3
MINIMUM_DETAIL_SAMPLE_SUCCESSES = 2


@dataclass(frozen=True)
class NoticeRuleSample:
    """상세 규칙 생성·검증에 사용할 목록 공지 한 건."""

    title: str
    url: str


def _get_gemini_api_token() -> str:
    """Crawl4AI LLM 호출에 사용할 Gemini API 키를 반환한다."""
    token = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not token:
        raise CrawlRuleGenerationError(
            "GOOGLE_API_KEY 또는 GEMINI_API_KEY가 필요합니다."
        )
    return token


async def fetch_html(url: str) -> str:
    """Crawl4AI로 페이지 HTML을 가져온다."""
    try:
        await asyncio.to_thread(validate_public_url, url)
    except UnsafeUrlError as error:
        raise CrawlRuleGenerationError(
            "안전하지 않은 URL은 크롤링할 수 없습니다."
        ) from error

    browser_config = BrowserConfig(headless=True, verbose=False)
    crawler_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=crawler_config)
    except Exception as error:
        raise CrawlRuleGenerationError(
            f"페이지 크롤링 실패: {error}"
        ) from error

    if not result.success or not result.html:
        raise CrawlRuleGenerationError(
            f"페이지 크롤링 실패: {result.error_message}"
        )

    return result.cleaned_html or result.html


def _generate_css_schema(
    html: str,
    query: str,
    target_json_example: str,
) -> CrawlRuleDefinition:
    """HTML과 추출 목표로 Crawl4AI CSS 스키마를 생성한다."""
    try:
        schema = JsonCssExtractionStrategy.generate_schema(
            html=html,
            schema_type="CSS",
            query=query,
            target_json_example=target_json_example,
            llm_config=LLMConfig(
                provider=GEMINI_FLASH_PROVIDER,
                api_token=_get_gemini_api_token(),
            ),
            validate=True,
            max_refinements=3,
        )
    except CrawlRuleGenerationError:
        raise
    except Exception as error:
        raise CrawlRuleGenerationError(
            f"CSS 스키마 생성 실패: {error}"
        ) from error

    if not isinstance(schema, dict):
        raise CrawlRuleGenerationError("generate_schema 결과가 객체가 아닙니다.")

    try:
        return CrawlRuleDefinition.model_validate(schema)
    except ValidationError as error:
        raise CrawlRuleGenerationError(
            "생성된 CSS 스키마가 올바르지 않습니다."
        ) from error


def generate_css_schema(html: str) -> CrawlRuleDefinition:
    """공지 목록 HTML에서 title과 url CSS 스키마를 생성한다."""
    return _generate_css_schema(
        html,
        LIST_SCHEMA_QUERY,
        LIST_SCHEMA_EXAMPLE,
    )


def generate_detail_css_schema(html: str) -> CrawlRuleDefinition:
    """공지 상세 HTML에서 title과 content CSS 스키마를 생성한다."""
    return _generate_css_schema(
        html,
        DETAIL_SCHEMA_QUERY,
        DETAIL_SCHEMA_EXAMPLE,
    )


def validate_css_rule(
    source_url: str,
    html: str,
    rule_definition: CrawlRuleDefinition,
) -> tuple[NoticeRuleSample, ...]:
    """목록 CSS 규칙을 검증하고 고유한 상세 공지 샘플을 반환한다."""
    field_names = {field.name for field in rule_definition.fields}
    if not {"title", "url"}.issubset(field_names):
        raise CrawlRuleValidationError(
            "크롤링 규칙에는 title과 url 필드가 필요합니다."
        )

    schema = rule_definition.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )

    try:
        items = JsonCssExtractionStrategy(schema).extract(source_url, html)
    except Exception as error:
        raise CrawlRuleValidationError(
            f"CSS 규칙 적용 실패: {error}"
        ) from error

    if not isinstance(items, list) or not items:
        raise CrawlRuleValidationError(
            "CSS 규칙으로 유효한 공지를 추출하지 못했습니다."
        )

    samples: tuple[NoticeRuleSample, ...] = ()
    seen_urls: frozenset[str] = frozenset()
    for item in items:
        if not isinstance(item, dict):
            continue

        title = item.get("title")
        url = item.get("url")
        if not isinstance(title, str) or not title.strip():
            continue
        if not isinstance(url, str) or not url.strip():
            continue

        absolute_url = urljoin(source_url, url.strip())
        if absolute_url in seen_urls:
            continue

        samples = (
            *samples,
            NoticeRuleSample(
                title=title.strip(),
                url=absolute_url,
            ),
        )
        seen_urls = frozenset((*seen_urls, absolute_url))

    if samples:
        return samples

    raise CrawlRuleValidationError(
        "CSS 규칙으로 유효한 공지를 추출하지 못했습니다."
    )


def validate_detail_css_rule(
    detail_url: str,
    html: str,
    rule_definition: CrawlRuleDefinition,
    list_title: str,
) -> tuple[str, str]:
    """상세 CSS 규칙이 실제 제목과 본문을 추출하는지 검증한다."""
    field_names = {field.name for field in rule_definition.fields}
    if not {"title", "content"}.issubset(field_names):
        raise CrawlRuleValidationError(
            "상세 크롤링 규칙에는 title과 content 필드가 필요합니다."
        )

    schema = rule_definition.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )
    try:
        items = JsonCssExtractionStrategy(schema).extract(detail_url, html)
    except Exception as error:
        raise CrawlRuleValidationError(
            f"상세 CSS 규칙 적용 실패: {error}"
        ) from error

    if not isinstance(items, list):
        items = []

    for item in items:
        if not isinstance(item, dict):
            continue
        extracted_title = item.get("title")
        content = item.get("content")
        title = (
            extracted_title.strip()
            if isinstance(extracted_title, str) and extracted_title.strip()
            else list_title.strip()
        )
        if title and isinstance(content, str) and content.strip():
            return title, content.strip()

    raise CrawlRuleValidationError(
        "상세 CSS 규칙으로 유효한 제목과 본문을 추출하지 못했습니다."
    )


async def generate_candidate(
    source: SourceResponse,
    rule_repository: SourceCrawlRuleRepository,
) -> SourceCrawlRuleResponse:
    """CSS 규칙을 생성·검증하고 active 상태로 전환한다."""
    source_url = str(source.url)
    html = await fetch_html(source_url)
    rule_definition = await asyncio.to_thread(generate_css_schema, html)
    samples = validate_css_rule(source_url, html, rule_definition)
    selected_samples = samples[:DETAIL_SAMPLE_COUNT]
    detail_pages: tuple[tuple[NoticeRuleSample, str], ...] = ()
    for sample in selected_samples:
        detail_pages = (
            *detail_pages,
            (sample, await fetch_html(sample.url)),
        )

    if not detail_pages:
        raise CrawlRuleValidationError("검증할 상세 페이지 샘플이없습니다.")

    detail_rule_definition = await asyncio.to_thread(
        generate_detail_css_schema,
        detail_pages[0][1],
    )
    candidate = rule_repository.create_candidate(
        SourceCrawlRuleCreate(
            source_id=source.id,
            rule_definition=rule_definition,
            detail_rule_definition=detail_rule_definition,
            generated_by=GeneratedBy.LLM,
        )
    )

    successful_validations = 0
    for sample, detail_html in detail_pages:
        try:
            validate_detail_css_rule(
                sample.url,
                detail_html,
                detail_rule_definition,
                sample.title,
            )
        except CrawlRuleValidationError:
            continue
        successful_validations += 1

    required_successes = min(
        MINIMUM_DETAIL_SAMPLE_SUCCESSES,
        len(detail_pages),
    )
    if successful_validations < required_successes:
        rule_repository.update_validation_status(
            candidate.id,
            ValidationStatus.FAILED,
        )
        raise CrawlRuleValidationError(
            "상세 CSS 규칙이 충분한 샘플에서 검증되지 않았습니다."
        )

    rule_repository.update_validation_status(
        candidate.id,
        ValidationStatus.PASSED,
    )
    return rule_repository.activate(candidate.id)
