import asyncio
import json
import os

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

GEMINI_FLASH_PROVIDER = "gemini/gemini-3.7-flash"
SCHEMA_QUERY = (
    "공지 목록의 각 행에서 제목(title)과 상세 페이지 링크(url)를 추출한다."
)
SCHEMA_EXAMPLE = json.dumps(
    {
        "title": "공지 제목",
        "url": "https://example.com/notice/1",
    },
    ensure_ascii=False,
)


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


def generate_css_schema(html: str) -> CrawlRuleDefinition:
    """HTML에서 Crawl4AI LLM으로 CSS 추출 스키마를 생성한다."""
    try:
        schema = JsonCssExtractionStrategy.generate_schema(
            html=html,
            schema_type="CSS",
            query=SCHEMA_QUERY,
            target_json_example=SCHEMA_EXAMPLE,
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


def validate_css_rule(
    source_url: str,
    html: str,
    rule_definition: CrawlRuleDefinition,
) -> None:
    """CSS 규칙이 HTML에서 title과 url을 실제로 추출하는지 검증한다."""
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

    for item in items:
        if not isinstance(item, dict):
            continue

        title = item.get("title")
        url = item.get("url")
        if (
            isinstance(title, str)
            and title.strip()
            and isinstance(url, str)
            and url.strip()
        ):
            return

    raise CrawlRuleValidationError(
        "CSS 규칙으로 유효한 공지를 추출하지 못했습니다."
    )


async def generate_candidate(
    source: SourceResponse,
    rule_repository: SourceCrawlRuleRepository,
) -> SourceCrawlRuleResponse:
    """CSS 규칙을 생성·검증하고 active 상태로 전환한다."""
    html = await fetch_html(str(source.url))
    rule_definition = await asyncio.to_thread(generate_css_schema, html)
    candidate = rule_repository.create_candidate(
        SourceCrawlRuleCreate(
            source_id=source.id,
            rule_definition=rule_definition,
            generated_by=GeneratedBy.LLM,
        )
    )

    try:
        validate_css_rule(str(source.url), html, rule_definition)
    except CrawlRuleValidationError:
        rule_repository.update_validation_status(
            candidate.id,
            ValidationStatus.FAILED,
        )
        raise

    rule_repository.update_validation_status(
        candidate.id,
        ValidationStatus.PASSED,
    )
    return rule_repository.activate(candidate.id)
