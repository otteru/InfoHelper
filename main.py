import asyncio

from dotenv import load_dotenv

from ai_graphs.ingestion_graph.graph import create_ingestion_graph
from ai_graphs.recommendation_graph.graph import create_recommendation_graph
from ai_graphs.shared.clients import (
    create_gemini_client,
    create_supabase_client,
)
from ai_graphs.shared.context import GraphContext

async def run_ingestion() -> None:
    """Ingestion Graph 실행 및 저장 결과 출력"""
    context = GraphContext(
        gemini_client=create_gemini_client(),
        supabase_client=create_supabase_client(),
    )
    
    graph = create_ingestion_graph()
    
    result = await graph.ainvoke(
        {},
        context=context,
    )
    
    saved_count = result.get("saved_count", 0)
    errors = result.get("errors", ())

    print(f"저장 완료 chunk 수: {saved_count}")

    if not errors:
        print("크롤링 오류 없음")
        return

    print(f"크롤링 실패 수: {len(errors)}")

    for error in errors:
        print(f"- {error}")


async def run_recommendation() -> None:
    """Recommendation Graph를 실행하고 추천 후보를 출력한다."""
    context = GraphContext(
        gemini_client=create_gemini_client(),
        supabase_client=create_supabase_client(),
    )

    graph = create_recommendation_graph()

    result = await graph.ainvoke(
        {},
        context=context,
    )

    candidates = result.get("candidates", ())
    print(f"추천 후보 수: {len(candidates)}")

    for index, candidate in enumerate(candidates, start=1):
        print(
            f"- {index}. {candidate.get('title')} "
            f"/ score={candidate.get('total_score')}"
        )


async def main() -> None:
    """프로젝트 실행 환경을 초기화한다."""
    load_dotenv()
    await run_ingestion()
    await run_recommendation()


if __name__ == "__main__":
    asyncio.run(main())
