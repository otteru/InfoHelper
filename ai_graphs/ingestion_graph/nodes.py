import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from langgraph.runtime import Runtime
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
USER_URL_PATH = PROJECT_ROOT / "data" / "userURL.json"


# Ingestion Graph workflow
# 1. data/userURL.json에서 공지 출처와 목록 URL을 불러온다.
#    - 이후에는 sources 테이블로 이전한다. 
# 2. Crawl4AI로 각 공지 목록 페이지를 가져온다.
# 3. 목록 페이지에서 상세 공지 URL을 추출한다.
# 4. Crawl4AI로 상세 공지 페이지를 가져온다.
# 5. 제목, 본문, URL을 Notice로 구조화한다.
# 6. 공지 본문을 임베딩 가능한 청크로 나눈다.
# 7. 각 청크의 임베딩을 생성한다.
# 8. (notice_id, chunk_index)를 기준으로 Supabase에 upsert한다.

def load_sources(state: IngestionState) -> dict[str, tuple[Source,...]]:
    """userURL.json에서 공지 출처 목록을 불러온다."""
    with USER_URL_PATH.open(encoding="utf-8") as file :
        data = json.load(file)
        
        sources = tuple(
                Source(
                    name=item["name"],
                    url=item["url"],
                )
                for item in data["resource"]
            )
        
        return {"sources": sources}
    
async def _crawl_throgh_crawl4ai(
    urls: list[str],
) -> list[Any | CrawlFailure]:
    """하나의 Crawl4AI 크롤러로 여러 URL을 크롤링한다."""
    if not urls:
        return []

    browser_config = BrowserConfig(headless=True, verbose=True)
    crawler_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, stream=False)

    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            results = await crawler.arun_many(
                urls=urls,
                config=crawler_config,
            )
    except Exception as error:
        message = f"{type(error).__name__}: {error}"

        return [
            CrawlFailure(url=url, message=message)
            for url in urls
        ]
        
    # stream으로 올 경우 비동기적으로 꺼내서 최종적으로 리스트로 만드는 문법
    # stream = False의 경우에는 이 조건문 통과
    if isinstance(results, AsyncIterator):
        return [result async for result in results]

    return list(results)
    
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

        links = result.links.get("internal", [])

        for link in links:
            href = link.get("href")

            if isinstance(href, str) and "artclView.do" in href:
                notice_targets = (
                    *notice_targets,
                    NoticeTarget(
                        source_id=source.name,
                        url=href,
                    ),
                )

    return {
        "notice_targets": notice_targets,
        "errors": errors,
    }

def _create_notice(
    target: NoticeTarget,
    result: Any,
) -> Notice:
    """Crawl4AI 결과를 Notice 객체로 변환한다."""
    if not result.success:
        raise ValueError(
            f"공지 크롤링에 실패했습니다: {result.error_message}"
        )

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
            continue

        notices = (*notices, notice)

    return {
        "notices": notices,
        "errors": errors,
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
        "source_id": notice.source_id,
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
