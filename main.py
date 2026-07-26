import asyncio

from dotenv import load_dotenv

from ai_graphs.ingestion_graph.context import IngestionContext
from ai_graphs.ingestion_graph.graph import create_ingestion_graph
from ai_graphs.shared.clients import (
    create_gemini_client,
    create_supabase_client,
)

async def run_ingestion() -> None:
    """Ingestion Graph 실행 및 저장 결과 출력"""
    context = IngestionContext(
        gemini_client=create_gemini_client(),
        supabase_client=create_supabase_client(),
    )
    
    graph = create_ingestion_graph()
    
    result = await graph.ainvoke(
        {},
        context=context,
    )
    
    saved_count = result.get("saved_count", 0)
    print(f"저장 완료 chunk 수: {saved_count}")


async def main() -> None:
    """프로젝트 실행 환경을 초기화한다."""
    load_dotenv()
    await run_ingestion()


if __name__ == "__main__":
    asyncio.run(main())