from collections.abc import Mapping
from pathlib import Path
from typing import cast

import frontmatter
from langgraph.runtime import Runtime
from openai import OpenAI

from ai_graphs.recommendation_graph.models import RetrievedChunk
from ai_graphs.recommendation_graph.state import RecommendationState
from ai_graphs.shared.context import GraphContext
from integrations.clients import create_embedding

PROJECT_ROOT = Path(__file__).resolve().parents[2]
USER_INFO_PATH = PROJECT_ROOT / "data" / "userInfo.md"
SIMILARITY_THRESHOLD = 0.65
RECOMMENDATION_SCORE_THRESHOLD = 0.6

# Recommendation Graph workflow
# 1. data/userInfo.md에서 사용자 프로필과 추천 검색어를 불러온다.
# 2. 목적별 추천 검색어를 각각 임베딩한다.
# 3. 검색어 임베딩으로 Supabase의 공지 청크를 검색한다.
# 4. 같은 공지에서 검색된 여러 청크를 notice_id 기준으로 통합한다.
# 5. 후보 점수가 추천 기준 이상이면 최종 recommendation으로 선정한다.

def load_user_info(state: RecommendationState) -> RecommendationState:
    """userInfo.md에서 User 정보와 query를 가져온다."""
    text = USER_INFO_PATH.read_text(encoding="utf-8")
    document = frontmatter.loads(text)

    query_data = document.metadata.get("recommendation_queries")

    # 여기서 검증하는 부분은 없어도 되지만 pylance가 query_data를 dictionary인지 알지 못해서 오류 나는 것 때문
    if not isinstance(query_data, Mapping):
        raise ValueError("recommendation_queries가 올바른 형식이 아닙니다.")

    queries = tuple(
        value
        for value in query_data.values()
        if isinstance(value, str)
    )

    if len(queries) != len(query_data):
        raise ValueError("모든 query는 문자열이어야 합니다.")

    return {
        "user_profile": document.content,
        "queries": queries,
    }

def _create_embedding(client: OpenAI, text: str) -> list[float]:
    """검색어를 OpenRouter 임베딩 벡터로 변환한다."""
    return create_embedding(client, f"text: {text}")


def _create_retrieved_chunk(
    row: Mapping[str, object],
    matched_query: str,
) -> RetrievedChunk:
    """Supabase RPC 응답을 검증해 RetrievedChunk로 변환한다."""
    notice_id = row.get("notice_id")
    title = row.get("title")
    url = row.get("url")
    content = row.get("content")
    similarity = row.get("similarity")

    if not isinstance(notice_id, str):
        raise ValueError("검색 결과에 올바른 notice_id가 없습니다.")

    if not isinstance(title, str):
        raise ValueError("검색 결과에 올바른 title이 없습니다.")

    if not isinstance(url, str):
        raise ValueError("검색 결과에 올바른 url이 없습니다.")

    if not isinstance(content, str):
        raise ValueError("검색 결과에 올바른 content가 없습니다.")

    if not isinstance(similarity, (int, float)):
        raise ValueError("검색 결과에 올바른 similarity가 없습니다.")

    return RetrievedChunk(
        notice_id=notice_id,
        title=title,
        url=url,
        content=content,
        similarity=float(similarity),
        matched_query=matched_query,
    )

def queries_search(
    state: RecommendationState,
    runtime: Runtime[GraphContext],
) -> RecommendationState:
    """목적별 추천 검색어를 각각 임베딩하고 유사한 공지 청크를 검색한다."""
    embedding_client = runtime.context.embedding_client
    supabase_client = runtime.context.supabase_client

    queries = state.get("queries", ())

    if not queries:
        raise ValueError("추천 검색어가 없습니다.")

    retrieved_chunks: tuple[RetrievedChunk, ...] = ()

    for query in queries:
        embedding = _create_embedding(
            embedding_client,
            text=query,
        )

        # supabase db에 등록된 "match_notice_chunks" RPC 함수를 호출
        response = supabase_client.rpc(
            "match_notice_chunks",
            {
                "query_embedding": embedding,
                "match_count": 20, # 상위 20개 같은 공고의 청크가 여러개 나올 수 있기에
            },
        ).execute()

        # response 예시
        # [
        #     {
        #         "notice_id": "https://example.com/notice/1",
        #         "chunk_index": 2,
        #         "title": "AI 해커톤 참가자 모집",
        #         "url": "https://example.com/notice/1",
        #         "content": "AI 서비스를 개발하는 해커톤입니다.",
        #         "deadline": None,
        #         "source_id": "건국대학교",
        #         "status": "open",
        #         "similarity": 0.87,
        #     },
        # ]

        rows = response.data

        if not isinstance(rows, list):
            raise ValueError("공지 청크 검색 결과가 list 형식이 아닙니다.")

        if any(not isinstance(row, Mapping) for row in rows):
            raise ValueError("공지 청크 검색 결과에 올바르지 않은 행이 있습니다.")

        parsed_chunks = tuple(
            _create_retrieved_chunk(
                row=row,
                matched_query=query,
            )
            for row in rows
            if isinstance(row, Mapping)
        )

        matched_chunks = tuple(
            chunk
            for chunk in parsed_chunks
            if chunk.similarity >= SIMILARITY_THRESHOLD
        )

        retrieved_chunks = (
            *retrieved_chunks,
            *matched_chunks
        )

    return {
        "retrieved_chunks": retrieved_chunks,
    }

def _create_candidate(
    notice_id: str,
    chunks: tuple[RetrievedChunk, ...],
    query_count: int,
) -> dict[str, object]:
    """같은 공지의 청크들을 하나의 추천 후보로 만든다."""
    if not chunks:
        raise ValueError("후보로 만들 공지 청크가 없습니다.")

    if query_count <= 0:
        raise ValueError("전체 query 수는 1개 이상이어야 합니다.")

    best_chunk = max(
        chunks,
        key=lambda chunk: chunk.similarity,
    )

    # 한 공지가 하나의 쿼리가 아니라 여러 쿼리에 해당되었을 수도 있다.
    matched_queries = tuple(
        dict.fromkeys(
            chunk.matched_query
            for chunk in chunks
        )
    )

    best_similarity = best_chunk.similarity
    # 해당 공지글이 몇 개의 쿼리에서 나왔는지를 나타낸다.
    query_coverage = len(matched_queries) / query_count
    total_score = (
        best_similarity * 0.8
        + query_coverage * 0.2
    )

    return {
        "notice_id": notice_id,
        "title": best_chunk.title,
        "url": best_chunk.url,
        "best_chunk": best_chunk.content,
        "matched_chunks": chunks,
        "matched_queries": matched_queries,
        "best_similarity": best_similarity,
        "query_coverage": query_coverage,
        "total_score": total_score,
    }

def merge_candidates(
    state: RecommendationState
) -> RecommendationState:
    """검색된 청크들을 notice_id별 후보로 통합하고 점수를 계산한다."""
    retrieved_chunks = state.get("retrieved_chunks")
    queries = state.get("queries")

    if not queries:
        raise ValueError("추천 검색어가 없습니다.")

    # 검색된 결과가 없는 것은 정상 처리
    if not retrieved_chunks:
        return {
            "candidates":(),
        }

    # notice_id 중복을 제거하면서 검색 순서를 유지한다.
    notice_ids = tuple(
        dict.fromkeys(
            chunk.notice_id
            for chunk in retrieved_chunks
        )
    )

    candidates = tuple(
        _create_candidate(
            notice_id = notice_id,
            chunks=tuple(
                chunk
                for chunk in retrieved_chunks
                if chunk.notice_id == notice_id
            ),
            query_count=len(queries)
        )
        for notice_id in notice_ids
    )

    sorted_candidates = tuple(
        sorted(
            candidates,
            key=lambda candidate: float(
                cast(int | float, candidate["total_score"])
            ),
            reverse=True
        )
    )

    return {
        "candidates": sorted_candidates
    }


def select_recommendations(
    state: RecommendationState,
) -> RecommendationState:
    """추천 기준 점수 이상인 후보를 최종 recommendation으로 선정한다."""
    candidates = state.get("candidates", ())

    if any(
        not isinstance(candidate.get("total_score"), (int, float))
        for candidate in candidates
    ):
        raise ValueError("후보에 올바른 total_score가 없습니다.")

    recommendations = tuple(
        candidate
        for candidate in candidates
        if cast(
            int | float,
            candidate["total_score"],
        ) >= RECOMMENDATION_SCORE_THRESHOLD
    )

    return {
        "recommendations": recommendations,
    }
