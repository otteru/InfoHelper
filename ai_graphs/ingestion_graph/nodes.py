import asyncio
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urljoin

from langgraph.runtime import Runtime
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
from google import genai
from google.genai import types
from supabase import Client

from ai_graphs.ingestion_graph.models import (
    CrawlFailure,
    Notice,
    NoticeTarget,
    Source,
)
from ai_graphs.ingestion_graph.state import IngestionState
from ai_graphs.shared.context import GraphContext
from app.repositories.source import SupabaseSourceRepository
from app.repositories.crawl_rule import SupabaseSourceCrawlRuleRepository
from integrations.url_safety import UnsafeUrlError, validate_public_url

# Ingestion Graph workflow
# 1. sources 테이블과 active 크롤링 규칙을 불러온다.
# 2. Crawl4AI로 각 공지 목록 페이지를 가져온다.
# 3. 목록 페이지에서 상세 공지 URL을 추출한다.
# 4. Crawl4AI로 상세 공지 페이지를 가져온다.
# 5. 제목, 본문, URL을 Notice로 구조화한다.
# 6. 공지 본문을 임베딩 가능한 청크로 나눈다.
# 7. 각 청크의 임베딩을 생성한다.
# 8. (notice_id, chunk_index)를 기준으로 Supabase에 upsert한다.

def load_sources(
    state: IngestionState,
    runtime: Runtime[GraphContext]) -> dict[str, tuple[Source,...]]:
    """sources와 active 크롤링 규칙을 불러온다."""
    source_repo = SupabaseSourceRepository(client=runtime.context.supabase_client)
    rule_repo = SupabaseSourceCrawlRuleRepository(client=runtime.context.supabase_client)

    loaded : list[Source] = []
    for row in source_repo.list_all():
        rule = rule_repo.get_active(row.id)
        if rule is None:
            continue
        loaded.append(
            Source(
                id=row.id,
                name=row.name,
                url=str(row.url),
                rule_definition=rule.rule_definition,
                detail_rule_definition=getattr(
                    rule,
                    "detail_rule_definition",
                    None,
                ),
            )
        )

    return {"sources": tuple(loaded)}

async def _crawl_throgh_crawl4ai(
    urls: list[str],
) -> list[Any | CrawlFailure]:
    """하나의 Crawl4AI 크롤러로 여러 URL을 크롤링한다."""
    if not urls:
        return []

    result_slots: list[Any | CrawlFailure | None] = [None] * len(urls)
    safe_urls: list[str] = []
    safe_indices: list[int] = []
    for index, url in enumerate(urls):
        try:
            await asyncio.to_thread(validate_public_url, url)
        except UnsafeUrlError as error:
            result_slots[index] = CrawlFailure(
                url=url,
                message=f"안전하지 않은 URL: {error}",
            )
            continue

        safe_urls.append(url)
        safe_indices.append(index)

    if not safe_urls:
        return [
            result
            for result in result_slots
            if result is not None
        ]

    browser_config = BrowserConfig(headless=True, verbose=True)
    crawler_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, stream=False)

    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            results = await crawler.arun_many(
                urls=safe_urls,
                config=crawler_config,
            )
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        for index, url in zip(safe_indices, safe_urls, strict=True):
            result_slots[index] = CrawlFailure(url=url, message=message)
    else:
        # stream으로 올 경우 비동기적으로 꺼내서 리스트로 만든다.
        if isinstance(results, AsyncIterator):
            crawled_results = [result async for result in results]
        else:
            crawled_results = list(results)

        aligned_results = _align_crawl_results(safe_urls, crawled_results)
        for index, result in zip(
            safe_indices,
            aligned_results,
            strict=True,
        ):
            result_slots[index] = result

    return [
        result
        if result is not None
        else CrawlFailure(
            url=urls[index],
            message="크롤링 결과를 만들지 못했습니다.",
        )
        for index, result in enumerate(result_slots)
    ]


def _align_crawl_results(
    requested_urls: list[str],
    crawled_results: list[Any],
) -> list[Any | CrawlFailure]:
    """Crawl4AI 결과를 결과 URL 기준으로 요청 순서에 맞춘다."""
    remaining_results: tuple[tuple[int, Any], ...] = tuple(
        enumerate(crawled_results)
    )
    aligned_results: list[Any | CrawlFailure] = []

    for url in requested_urls:
        matching_result = next(
            (
                (index, result)
                for index, result in remaining_results
                if getattr(result, "url", None) == url
            ),
            None,
        )
        if matching_result is None:
            aligned_results.append(
                CrawlFailure(
                    url=url,
                    message="요청 URL과 일치하는 Crawl4AI 결과가 없습니다.",
                )
            )
            continue

        matched_index, result = matching_result
        aligned_results.append(result)
        remaining_results = tuple(
            (index, remaining_result)
            for index, remaining_result in remaining_results
            if index != matched_index
        )

    return aligned_results

async def crawl_source_page(state: IngestionState) -> IngestionState:
    """공지 목록 페이지에서 상세 공지 URL을 추출한다."""
    sources = state.get("sources")

    if sources is None:
        raise ValueError("sources가 없습니다.")

    # Crawl4AI가 URL 목록을 동시 크롤링하고 결과를 반환한다.
    results = await _crawl_throgh_crawl4ai(
        [source.url for source in sources],
    )

    notice_targets: tuple[NoticeTarget, ...] = ()
    errors = state.get("errors", ())

    for source, result in zip(sources, results, strict=True):
        if isinstance(result, CrawlFailure):
            errors = (*errors, f"{result.url}: {result.message}")
            continue

        if not result.success:
            error_message = result.error_message or "알 수 없는 크롤링 오류"
            errors = (*errors, f"{source.url}: {error_message}")
            continue

        html = result.cleaned_html or result.html

        if not html:
            errors = (*errors, f"{source.url}: 목록 HTML이 없습니다.")
            continue

        try:
            extracted = _notice_targets_from_html(source, html)
        except Exception as error:
            errors = (
                *errors,
                f"{source.url}: {type(error).__name__}: {error}",
            )
            continue

        notice_targets = (*notice_targets, *extracted)

    return {
        "notice_targets": notice_targets,
        "errors": errors,
    }

def _notice_targets_from_html(
    source: Source,
    html: str,
) -> tuple[NoticeTarget, ...]:
    """CSS 규칙으로 목록 HTML에서 상세 공지 URL을 추출한다."""
    schema = source.rule_definition.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True, #None인 값을 아예 생략
    )
    items = JsonCssExtractionStrategy(schema).extract(source.url, html)

    targets: tuple[NoticeTarget, ...] = ()
    seen_urls: frozenset[str] = frozenset()
    for item in items:
        if not isinstance(item, dict):
            continue
        href = item.get("url")
        if not isinstance(href, str) or not href:
            continue
        extracted_title = item.get("title")
        title = (
            extracted_title.strip()
            if isinstance(extracted_title, str) and extracted_title.strip()
            else None
        )
        url = urljoin(source.url, href)
        if url in seen_urls:
            continue

        targets = (
            *targets,
            NoticeTarget(
                source_id=source.id,
                url=url,
                title=title,
                detail_rule_definition=source.detail_rule_definition,
            ),
        )
        seen_urls = frozenset((*seen_urls, url))
    return targets


def _create_notice(
    target: NoticeTarget,
    result: Any,
) -> Notice:
    """Crawl4AI 결과를 Notice 객체로 변환한다."""
    if not result.success:
        raise ValueError(
            f"공지 크롤링에 실패했습니다: {result.error_message}"
        )

    if target.detail_rule_definition is not None:
        return _create_notice_with_detail_rule(target, result)

    if result.markdown is None:
        raise ValueError("공지 Markdown 결과가 없습니다.")

    metadata = result.metadata or {}
    metadata_title = metadata.get("title")

    title = (
        metadata_title.strip()
        if isinstance(metadata_title, str)
        and metadata_title.strip()
        else "제목 없음"
    )

    content = result.markdown.raw_markdown.strip()

    if not content:
        raise ValueError("공지 본문이 비어 있습니다.")

    return Notice(
        source_id=target.source_id,
        url=target.url,
        title=title,
        content=content,
        deadline=None,
    )


def _create_notice_with_detail_rule(
    target: NoticeTarget,
    result: Any,
) -> Notice:
    """상세 CSS 규칙으로 공지 제목과 본문을 추출한다."""
    html = result.cleaned_html or result.html
    if not html:
        raise ValueError("공지 상세 HTML이 없습니다.")

    rule_definition = target.detail_rule_definition
    if rule_definition is None:
        raise ValueError("공지 상세 크롤링 규칙이 없습니다.")

    schema = rule_definition.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )
    try:
        items = JsonCssExtractionStrategy(schema).extract(target.url, html)
    except Exception as error:
        raise ValueError(f"공지 상세 CSS 규칙 적용 실패: {error}") from error

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
            else (target.title or "").strip()
        )
        if title and isinstance(content, str) and content.strip():
            return Notice(
                source_id=target.source_id,
                url=target.url,
                title=title,
                content=content.strip(),
                deadline=None,
            )

    raise ValueError("공지 상세 CSS 규칙으로 제목과 본문을 추출하지 못했습니다.")

async def crawl_notice_pages(state: IngestionState) -> IngestionState:
    """상세 공지를 크롤링하고 성공한 공지만 반환한다."""
    notice_targets = state.get("notice_targets")

    if notice_targets is None:
        raise ValueError("notice_targets가 없습니다.")

    results = await _crawl_throgh_crawl4ai(
        [target.url for target in notice_targets],
    )

    notices: tuple[Notice, ...] = ()
    errors = state.get("errors", ())
    invalid_notice_ids = state.get("invalid_notice_ids", ())

    for target, result in zip(notice_targets, results, strict=True):
        if isinstance(result, CrawlFailure):
            errors = (*errors, f"{result.url}: {result.message}")
            continue

        if not result.success:
            error_message = result.error_message or "알 수 없는 크롤링 오류"
            errors = (*errors, f"{target.url}: {error_message}")
            continue

        try:
            notice = _create_notice(target, result)
        except ValueError as error:
            errors = (*errors, f"{target.url}: {error}")
            invalid_notice_ids = (*invalid_notice_ids, target.url)
            continue

        notices = (*notices, notice)

    return {
        "notices": notices,
        "errors": errors,
        "invalid_notice_ids": invalid_notice_ids,
    }

def _split_text(text:str, chunk_size: int = 1000) -> list[str] :

    return [
        text[index:index + chunk_size]
        for index in range(0, len(text), chunk_size)
        if text[index:index + chunk_size].strip()
    ]

def _create_embedding(client: genai.Client, title: str, text: str) -> list[float]:
    content = f"title: {title} | text: {text}"

    response = client.models.embed_content(
        model="gemini-embedding-2",
        contents=content,
        config=types.EmbedContentConfig(output_dimensionality=1536),
    )

    if not response.embeddings:
        raise ValueError("임베딩 결과가 비어 있습니다.")

    values = response.embeddings[0].values
    if not values:
        raise ValueError("임베딩 값을 가져오지 못했습니다.")

    return values

def _save_chunk(
    supabase: Client ,
    notice: Notice,
    chunk_index: int,
    chunk: str,
    embedding: list[float],
) -> None:

    supabase.table("notice_chunks").upsert({
        "notice_id": notice.url,
        "chunk_index": chunk_index,
        "title": notice.title,
        "url": notice.url,
        "content": chunk,
        "deadline": (
            notice.deadline.isoformat()
            if notice.deadline is not None
            else None
        ),
        "source_id": str(notice.source_id),
        "status": "open",
        "embedding": embedding,
        },
        # notice_id와 chunk_index 조합이 이미 존재하면
        # 새 행을 insert하지 말고 기존 행을 update해라.
        on_conflict="notice_id,chunk_index",
    ).execute()

def _delete_stale_chunks(
    supabase: Client,
    notice_id: str,
    chunk_count: int,
) -> None:
    """ 새 청크 개수보다 큰 기존 청크를 삭제한다."""
    # eq = equal
    # gte = greater than or equal
    supabase.table("notice_chunks").delete().eq(
        "notice_id", notice_id,
    ).gte(
        "chunk_index", chunk_count,
    ).execute()


def _delete_invalid_notice_chunks(
    supabase: Client,
    notice_ids: tuple[str, ...],
) -> None:
    """상세 추출에 실패한 공지의 기존 청크를 삭제한다."""
    for notice_id in dict.fromkeys(notice_ids):
        (
            supabase.table("notice_chunks")
            .delete()
            .eq("notice_id", notice_id)
            .execute()
        )

def upsert_to_vectorDB(
    state: IngestionState,
    runtime: Runtime[GraphContext]
) -> dict[str, int]:
    """공지 본문을 chunk로 나누고 임베딩 생성 후 Supabase에 upsert"""
    notices = state.get("notices")

    if notices is None:
        raise ValueError("notices가 없습니다")

    gemini_client = runtime.context.gemini_client
    supabase = runtime.context.supabase_client
    invalid_notice_ids = state.get("invalid_notice_ids", ())

    _delete_invalid_notice_chunks(supabase, invalid_notice_ids)

    saved_count = 0

    for notice in notices:
        chunks = _split_text(notice.content, chunk_size=1000)

        for chunk_index, chunk in enumerate(chunks):
            embedding = _create_embedding(gemini_client, notice.title, chunk)
            _save_chunk(supabase, notice, chunk_index, chunk, embedding)
            saved_count += 1

        _delete_stale_chunks(
            supabase,
            notice_id=notice.url,
            chunk_count=len(chunks),
        )

    return {"saved_count": saved_count}
