from typing import NotRequired, TypedDict

from ai_graphs.recommendation_graph.models import RetrievedChunk


class RecommendationState(TypedDict):
    """Recommendation Graph 노드 사이에서 전달하는 상태."""

    user_profile: NotRequired[str]
    queries: NotRequired[tuple[str, ...]]
    retrieved_chunks: NotRequired[tuple[RetrievedChunk, ...]]
    candidates: NotRequired[tuple[dict[str, object], ...]]
    recommendations: NotRequired[tuple[dict[str, object], ...]]
    errors: NotRequired[tuple[str, ...]]
