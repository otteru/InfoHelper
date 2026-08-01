from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from google import genai
from supabase import Client

from ai_graphs.recommendation_graph import nodes
from ai_graphs.recommendation_graph.graph import create_recommendation_graph
from ai_graphs.shared.context import GraphContext


class FakeGeminiModels:
    """고정된 query 임베딩을 반환하는 Gemini models 대역."""

    def embed_content(self, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            embeddings=[
                SimpleNamespace(values=[0.1] * 1536),
            ],
        )


class FakeGeminiClient:
    """Recommendation Graph 테스트용 Gemini 클라이언트."""

    def __init__(self) -> None:
        self.models = FakeGeminiModels()


class FakeRpcRequest:
    """Supabase RPC 실행 결과를 반환하는 요청 대역."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=self._rows)


class FakeSupabaseClient:
    """공지 청크 검색 결과를 반환하는 Supabase 클라이언트."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def rpc(
        self,
        function_name: str,
        params: dict[str, object],
    ) -> FakeRpcRequest:
        assert function_name == "match_notice_chunks"
        assert params["match_count"] == 20
        return FakeRpcRequest(self._rows)


def _create_context(
    rows: list[dict[str, object]],
) -> GraphContext:
    return GraphContext(
        gemini_client=cast(genai.Client, FakeGeminiClient()),
        supabase_client=cast(Client, FakeSupabaseClient(rows)),
    )


def _write_user_info(path: Path) -> None:
    path.write_text(
        """---
recommendation_queries:
  career: AI 관련 프로그램
  global: 글로벌 개발자 프로그램
---

# 테스트 사용자

AI와 글로벌 프로그램에 관심이 있다.
""",
        encoding="utf-8",
    )


def test_recommendation_graph가_검색_결과를_공지별_후보로_통합한다(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """검색 임계값을 적용하고 같은 공지의 청크를 하나로 통합한다."""
    user_info_path = tmp_path / "userInfo.md"
    _write_user_info(user_info_path)
    monkeypatch.setattr(nodes, "USER_INFO_PATH", user_info_path)

    rows: list[dict[str, object]] = [
        {
            "notice_id": "notice-a",
            "title": "AI 해커톤",
            "url": "https://example.com/a",
            "content": "AI 서비스를 만드는 해커톤입니다.",
            "similarity": 0.9,
        },
        {
            "notice_id": "notice-a",
            "title": "AI 해커톤",
            "url": "https://example.com/a",
            "content": "글로벌 참가자를 모집합니다.",
            "similarity": 0.7,
        },
        {
            "notice_id": "notice-b",
            "title": "일반 공지",
            "url": "https://example.com/b",
            "content": "일반 안내입니다.",
            "similarity": 0.64,
        },
    ]

    result = create_recommendation_graph().invoke(
        {},
        context=_create_context(rows),
    )

    assert result["queries"] == (
        "AI 관련 프로그램",
        "글로벌 개발자 프로그램",
    )
    assert len(result["retrieved_chunks"]) == 4
    assert len(result["candidates"]) == 1
    assert len(result["recommendations"]) == 1

    candidate = result["candidates"][0]
    assert candidate["notice_id"] == "notice-a"
    assert candidate["best_similarity"] == pytest.approx(0.9)
    assert candidate["query_coverage"] == pytest.approx(1.0)
    assert candidate["total_score"] == pytest.approx(0.92)
    assert result["recommendations"][0] == candidate


def test_rpc_검색_결과의_필수_필드가_없으면_실패한다() -> None:
    """Supabase 응답을 내부 모델로 변환할 때 필수 필드를 검증한다."""
    with pytest.raises(
        ValueError,
        match="올바른 content가 없습니다",
    ):
        nodes._create_retrieved_chunk(
            row={
                "notice_id": "notice-a",
                "title": "AI 해커톤",
                "url": "https://example.com/a",
                "similarity": 0.9,
            },
            matched_query="AI 관련 프로그램",
        )


def test_검색된_청크가_없으면_빈_후보를_반환한다() -> None:
    """검색 결과 0건을 오류가 아닌 정상 결과로 처리한다."""
    result = nodes.merge_candidates(
        {
            "queries": ("AI 관련 프로그램",),
            "retrieved_chunks": (),
        }
    )

    assert result["candidates"] == ()


def test_추천_점수_threshold_이상인_후보만_선정한다() -> None:
    """경계값을 포함해 기준 점수 이상인 후보만 recommendation으로 만든다."""
    result = nodes.select_recommendations(
        {
            "candidates": (
                {"notice_id": "high", "total_score": 0.61},
                {"notice_id": "boundary", "total_score": 0.6},
                {"notice_id": "low", "total_score": 0.59},
            ),
        }
    )

    assert tuple(
        recommendation["notice_id"]
        for recommendation in result["recommendations"]
    ) == (
        "high",
        "boundary",
    )
