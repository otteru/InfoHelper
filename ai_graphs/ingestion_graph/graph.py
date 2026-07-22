from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ai_graphs.ingestion_graph.nodes import (
    crawl_notice_pages,
    crawl_source_page,
    filter_existing_notices,
    load_sources,
    upsert_to_vectorDB,
)
from ai_graphs.ingestion_graph.state import IngestionState


def create_ingestion_graph() -> CompiledStateGraph:
    """공지 크롤링·임베딩·저장 워크플로우를 생성한다."""
    builder = StateGraph(IngestionState)

    builder.add_node("load_sources", load_sources)
    builder.add_node("crawl_source_page", crawl_source_page)
    builder.add_node(
        "filter_existing_notices",
        filter_existing_notices,
    )
    builder.add_node("crawl_notice_pages", crawl_notice_pages)
    builder.add_node("upsert_to_vector_db", upsert_to_vectorDB)

    builder.add_edge(START, "load_sources")
    builder.add_edge("load_sources", "crawl_source_page")
    builder.add_edge(
        "crawl_source_page",
        "filter_existing_notices",
    )
    builder.add_edge(
        "filter_existing_notices",
        "crawl_notice_pages",
    )
    builder.add_edge(
        "crawl_notice_pages",
        "upsert_to_vector_db",
    )
    builder.add_edge("upsert_to_vector_db", END)

    return builder.compile()
