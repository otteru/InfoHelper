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
from ai_graphs.ingestion_graph.context import IngestionContext


def create_ingestion_graph() -> CompiledStateGraph[
    IngestionState,
    IngestionContext,
    IngestionState,
    IngestionState,
]: # 이렇게 하지 않으면 main에서 ainvoke할 때 context를 None으로 추론해서 pylance 에러 발생
    """공지 크롤링·임베딩·저장 워크플로우를 생성한다."""
    builder = StateGraph(
        IngestionState,
        context_schema=IngestionContext,    
    )

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
