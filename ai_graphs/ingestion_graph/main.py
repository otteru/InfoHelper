import asyncio

from ai_graphs.ingestion_graph.graph import create_ingestion_graph


async def main() -> None:
    """Ingestion Graph를 실행하고 저장 결과를 출력한다."""
    graph = create_ingestion_graph()
    result = await graph.ainvoke({})

    saved_count = result.get("saved_count", 0)
    print(f"저장 완료 chunk 수: {saved_count}")


if __name__ == "__main__":
    asyncio.run(main())
