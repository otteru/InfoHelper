import asyncio
import json
import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CrawlerRunConfig,
    LLMConfig,
)
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
from pydantic import ValidationError

from app.exceptions import CrawlRuleGenerationError, CrawlRuleValidationError
from app.repositories.crawl_rule import SourceCrawlRuleRepository
from app.schemas.crawl_rule import (
    CrawlMode,
    CrawlRuleBaseField,
    CrawlRuleDefinition,
    CrawlRuleField,
    GeneratedBy,
    SourceCrawlRuleCreate,
    SourceCrawlRuleResponse,
    ValidationStatus,
)
from integrations.clients import (
    CRAWL4AI_GENERATION_PROVIDER,
    OPENROUTER_BASE_URL,
)
from integrations.crawl_config import create_crawler_run_config
from app.schemas.source import SourceResponse
from integrations.url_safety import UnsafeUrlError, validate_public_url

LIST_SCHEMA_QUERY = (
    "페이지에서 반복되는 개별 공고/공지 카드를 하나의 항목으로 본다. "
    "레이아웃이 테이블 행이든 리스트든 카드 그리드든 상관없다. "
    "각 항목에서 title(사람이 읽는 제목)과 url(그 항목 상세로 가는 링크)만 추출한다. "
    "메뉴, 북마크, 로그인, 회사 소개, 필터, 푸터 링크는 제외한다. "
    "url은 항목 자체의 상세 링크여야 하며, 가능하면 href 경로 패턴처럼 안정적인 선택자를 쓴다. "
    "해시된 class, 유틸리티 class만으로 항목을 구분하지 않는다. "
    # 직행처럼 카드 루트가 a인 경우, 자식 a를 찾으면 href가 비어 422가 난다.
    "항목의 반복 단위가 이미 a 태그이면 url은 자식 a가 아니라 그 a의 href에서 가져온다. "
    "이때 url은 fields가 아니라 baseFields로 둔다."
)
LIST_SCHEMA_EXAMPLE = json.dumps(
    {
        "title": "항목 제목",
        "url": "https://example.com/item/123",
    },
    ensure_ascii=False,
)
DETAIL_SCHEMA_QUERY = (
    "이 페이지의 본문인 공고/공지 상세만 추출한다. "
    "title은 해당 공고의 실제 제목, content는 본문 전체다. "
    "사이트 메뉴, 헤더, 푸터, 이전/다음 글, 관련 공고 목록, 추천 카드는 제외한다."
)
DETAIL_SCHEMA_EXAMPLE = json.dumps(
    {
        "title": "항목 제목",
        "content": "공고 또는 공지의 실제 본문 내용",
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


def _get_openrouter_api_token() -> str:
    """Crawl4AI LLM 호출에 사용할 OpenRouter API 키를 반환한다."""
    token = os.environ.get("OPENROUTER_API_KEY")
    if not token:
        raise CrawlRuleGenerationError("OPENROUTER_API_KEY가 필요합니다.")
    return token


async def fetch_html(
    url: str,
    crawl_mode: CrawlMode = CrawlMode.DEFAULT,
) -> str:
    """Crawl4AI로 페이지 HTML을 가져온다."""
    try:
        await asyncio.to_thread(validate_public_url, url)
    except UnsafeUrlError as error:
        raise CrawlRuleGenerationError(
            "안전하지 않은 URL은 크롤링할 수 없습니다."
        ) from error

    browser_config = BrowserConfig(headless=True, verbose=False)
    crawler_config = create_crawler_run_config(crawl_mode)

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


async def _generate_css_schema(
    html: str,
    query: str,
    target_json_example: str,
) -> CrawlRuleDefinition:
    """HTML과 추출 목표로 Crawl4AI CSS 스키마를 생성한다."""
    try:
        schema = await JsonCssExtractionStrategy.agenerate_schema(
            html=html,
            schema_type="CSS",
            query=query,
            target_json_example=target_json_example,
            llm_config=LLMConfig(
                provider=CRAWL4AI_GENERATION_PROVIDER,
                api_token=_get_openrouter_api_token(),
                base_url=OPENROUTER_BASE_URL,
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


_ANCHOR_SELECTOR_PATTERN = re.compile(r"^a($|[.#\[:])")


def _selector_subject(selector: str) -> str:
    """CSS 선택자가 실제로 가리키는 마지막 태그 조각을 반환한다."""
    first_group = selector.strip().split(",")[0].strip()
    parts = re.split(r"\s*[>+~\s]\s*", first_group)
    return parts[-1] if parts else first_group


def _is_anchor_selector(selector: str) -> bool:
    """선택자 대상 태그가 a인지 확인한다."""
    return bool(_ANCHOR_SELECTOR_PATTERN.match(_selector_subject(selector)))


def _is_descendant_anchor_url_field(field: CrawlRuleField) -> bool:
    """url 필드가 자식 a의 href를 찾도록 생성된 경우인지 확인한다."""
    if field.name != "url" or field.type != "attribute" or field.attribute != "href":
        return False
    return _is_anchor_selector(field.selector)


def _normalize_root_link_url(rule: CrawlRuleDefinition) -> CrawlRuleDefinition:
    """루트가 a인데 url이 자식 a를 가리키면 루트 href(baseFields)로 옮긴다.

    LLM이 baseSelector를 a로 잡은 뒤 fields.url.selector를 다시 a로 두면
    중첩 a가 없어 href가 비고 목록 검증이 실패한다.
    """
    if not _is_anchor_selector(rule.base_selector):
        return rule

    remaining_fields = tuple(
        field
        for field in rule.fields
        if not _is_descendant_anchor_url_field(field)
    )
    if remaining_fields == rule.fields or not remaining_fields:
        return rule

    existing_base_fields = rule.base_fields or ()
    if any(field.name == "url" for field in existing_base_fields):
        base_fields = existing_base_fields
    else:
        base_fields = (
            *existing_base_fields,
            CrawlRuleBaseField(name="url", type="attribute", attribute="href"),
        )

    return rule.model_copy(
        update={
            "fields": remaining_fields,
            "base_fields": base_fields,
        }
    )


async def generate_css_schema(html: str) -> CrawlRuleDefinition:
    """공지 목록 HTML에서 title과 url CSS 스키마를 생성한다."""
    rule = await _generate_css_schema(
        html,
        LIST_SCHEMA_QUERY,
        LIST_SCHEMA_EXAMPLE,
    )
    return _normalize_root_link_url(rule)


async def generate_detail_css_schema(html: str) -> CrawlRuleDefinition:
    """공지 상세 HTML에서 title과 content CSS 스키마를 생성한다."""
    return await _generate_css_schema(
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
    field_names = {
        *(field.name for field in (rule_definition.base_fields or ())),
        *(field.name for field in rule_definition.fields),
    }
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
    list_crawl_mode: CrawlMode = CrawlMode.DEFAULT,
    detail_crawl_mode: CrawlMode = CrawlMode.DEFAULT,
) -> SourceCrawlRuleResponse:
    """CSS 규칙을 생성·검증하고 active 상태로 전환한다."""
    source_url = str(source.url)
    html = await fetch_html(source_url, list_crawl_mode)
    rule_definition = await generate_css_schema(html)
    samples = validate_css_rule(source_url, html, rule_definition)
    selected_samples = samples[:DETAIL_SAMPLE_COUNT]
    detail_pages: tuple[tuple[NoticeRuleSample, str], ...] = ()
    for sample in selected_samples:
        detail_pages = (
            *detail_pages,
            (sample, await fetch_html(sample.url, detail_crawl_mode)),
        )

    if not detail_pages:
        raise CrawlRuleValidationError("검증할 상세 페이지 샘플이없습니다.")

    detail_rule_definition = await generate_detail_css_schema(
        detail_pages[0][1],
    )
    candidate = rule_repository.create_candidate(
        SourceCrawlRuleCreate(
            source_id=source.id,
            rule_definition=rule_definition,
            detail_rule_definition=detail_rule_definition,
            list_crawl_mode=list_crawl_mode,
            detail_crawl_mode=detail_crawl_mode,
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
