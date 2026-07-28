from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ai_graphs.recommendation_graph.nodes import (
    load_user_info,
    merge_candidates,
    queries_search,
)
from ai_graphs.recommendation_graph.state import RecommendationState
from ai_graphs.shared.context import GraphContext


def create_recommendation_graph() -> CompiledStateGraph[
    RecommendationState,
    GraphContext,
    RecommendationState,
    RecommendationState,
]:
    """사용자 정보와 공지 청크를 매칭하는 추천 워크플로우를 생성한다."""
    builder = StateGraph(
        RecommendationState,
        context_schema=GraphContext,
    )

    builder.add_node("load_user_info", load_user_info)
    builder.add_node("queries_search", queries_search)
    builder.add_node("merge_candidates", merge_candidates)

    builder.add_edge(START, "load_user_info")
    builder.add_edge("load_user_info", "queries_search")
    builder.add_edge("queries_search", "merge_candidates")
    builder.add_edge("merge_candidates", END)

    return builder.compile()
