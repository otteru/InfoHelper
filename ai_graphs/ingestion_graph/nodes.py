from ai_graphs.ingestion_graph.state import IngestionState
from ai_graphs.ingestion_graph.models import Notice, NoticeTarget, Source
import json
import os
import asyncio
from typing import Any
from dotenv import load_dotenv
from pathlib import Path

from google import genai
from google.genai import types
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from supabase import create_client, Client

PROJECT_ROOT = Path(__file__).resolve().parents[2]
USER_URL_PATH = PROJECT_ROOT / "userURL.json"



# ================================================================
# Ingestion Graph workflow
# 1. userURL.json에서 공지 출처와 목록 URL을 불러온다.
#    - 이후에는 sources 테이블로 이전한다. 
# 2. Crawl4AI로 각 공지 목록 페이지를 가져온다.
# 3. 목록 페이지에서 상세 공지 URL을 추출한다.
# 4. Supabase에 이미 저장된 공지는 제외한다.
# 5. 새 공지의 상세 페이지를 Crawl4AI로 가져온다.
# 6. 제목, 본문, URL, 작성일, 마감일을 정제해 Notice로 구조화한다.
# 7. 공지 본문을 임베딩 가능한 chunk로 나눈다.
# 8. 각 chunk의 임베딩을 생성한다.
# 9. 임베딩과 공지 메타데이터를 Supabase에 upsert한다.
# ================================================================

load_dotenv()

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
    
async def _crawl_throgh_crawl4ai(url: str):
    """craw4ai를 이용해서 크롤링 결과 반환하는 도구 함수"""
    browser_config = BrowserConfig(headless=True, verbose=True)
    crawler_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=crawler_config)
        
        if not result.success:
            raise RuntimeError(f"크롤링 실패: {result.error_message}")
        
        return result 
    
async def crawl_source_page(state: IngestionState) -> dict[str, tuple[NoticeTarget, ...]]:
    """공지 페이지에서 공지 url들 추출"""
    sources = state.get("sources")
    
    if sources is None:
        raise ValueError("sources가 없습니다. load_sources 노드를 먼저 실행하세요")
    
    # 여러 비동기 작업을 동시에 실행하고, 전부 끝날 때까지 기다리는 함수
    # *는 튜플이나 리스트 안의 값을 함수 인자로 하나씩 펼치는 연산자
    results = await asyncio.gather(
        *(
            _crawl_throgh_crawl4ai(source.url)
            for source in sources
        )
    )
    
    # zip()은 여러 묶음에서 같은 순서의 값을 하나씩 짝지어 줍니다. 
    # strict=True는 두 묶음의 길이가 다르면 오류를 내는 옵션
    notice_targets = tuple(
        NoticeTarget(
            source_id=source.name,
            url=link["href"],
        )
        for source, result in zip(sources, results, strict = True)
        for link in result.links.get("internal", [])
        #TODO artclView.do는 건국대 공지사항에 맞춘 하드 코딩 추후 확장할 때 수정해야 함
        if "artclView.do" in link["href"]
    )
    
    return {"notice_targets": notice_targets}

def _find_existing_notice_ids(
    supabase: Client,
    notice_targets: tuple[NoticeTarget, ...],
) -> frozenset[str]:
    """Supabase에 이미 저장된 공지 URL 조회 및 반환"""
    urls = [target.url for target in notice_targets]
    
    # frozenset = 불변 set
    if not urls:
        return frozenset()
    
    response = (
        supabase.table("notice_chunks")
        .select("notice_id")
        .in_("notice_id", urls) # WHERE notice_id IN (urls)
        .execute()
    )
    
    return frozenset(
        str(row["notice_id"])
        
        for row in response.data or []
        if isinstance(row, dict)
        and isinstance(
            notice_id := row.get("notice_id"),
            str
        )
    )
    
#TODO 매번 client 생성이 아니라 한 곳에서 호출하여 싱글톤으로 사용되게 해야 함
def create_supabase_client() -> Client:
    """supabase client 생성"""
    supabase_url = f"https://{os.environ["supabase_project_id"]}.supabase.co"
    supabase_secret_key = os.environ["supabase_secret_key"]
    supabase_client = create_client(supabase_url, supabase_secret_key)
    
    return supabase_client
    


def filter_existing_notices(
    state: IngestionState,
) -> dict[str, tuple[NoticeTarget, ...]]:
    """이미 저장된 공지는 제외"""
    
    notice_targets = state.get("notice_targets")
    
    if notice_targets is None:
        raise ValueError("notice_targets가 없습니다")
    
    existing_notice_ids = _find_existing_notice_ids(
        supabase=create_supabase_client(),
        notice_targets=notice_targets
    )
    
    new_notice_targets = tuple(
        target
        for target in notice_targets
        if target.url not in existing_notice_ids
    )
    
    return {"notice_targets": new_notice_targets}


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

async def crawl_notice_pages(state: IngestionState) -> dict[str, tuple[Notice, ...]]:
    """각각의 공지글을 크롤링"""
    notice_targets = state.get("notice_targets")
    
    if notice_targets is None:
        raise ValueError("notice_targets가 없습니다")
    
    
    results = await asyncio.gather(
        *(
            _crawl_throgh_crawl4ai(target.url)
            for target in notice_targets
        )
    )

    notices = tuple(
        _create_notice(target, result)
        for target, result in zip(
            notice_targets,
            results,
            strict=True
        )
    )
    
    return {"notices": tuple(notices)}

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
    chunk: str,
    embedding: list[float],
) -> None:
    
    supabase.table
    supabase.table("notice_chunks").insert({
        "notice_id": notice.url,
        "title": notice.title,
        "url": notice.url,
        "content": chunk,
        "deadline": None,
        "source_id": notice.source_id,
        "status": "open",
        "embedding": embedding,
    }).execute()
    
def upsert_to_vectorDB(state: IngestionState) -> dict[str, int]:
    """공지 본문을 chunk로 나누고 임베딩 생성 후 Supabase에 upsert"""
    notices = state.get("notices")
    
    if notices is None:
        raise ValueError("notices가 없습니다")
    
    gemini_client = genai.Client(api_key = os.environ["gemini-api-key"])
    supabase = create_supabase_client()
    
    saved_count = 0
    
    for notice in notices:
        chunks = _split_text(notice.content, chunk_size=1000)
        
        for chunk in chunks:
            embedding = _create_embedding(gemini_client, notice.title, chunk)
            _save_chunk(supabase, notice, chunk, embedding)
            saved_count += 1
            
    return {"saved_count": saved_count}
            
    