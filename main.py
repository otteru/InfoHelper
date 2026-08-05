import asyncio
import os
from typing import TYPE_CHECKING, cast

import boto3
from dotenv import load_dotenv

if TYPE_CHECKING:
    from mypy_boto3_sesv2.client import SESV2Client

from ai_graphs.ingestion_graph.graph import create_ingestion_graph
from ai_graphs.recommendation_graph.graph import create_recommendation_graph
from ai_graphs.shared.clients import (
    create_gemini_client,
    create_supabase_client,
)
from ai_graphs.shared.context import GraphContext
from delivery.history import (
    DeliveryHistory,
    SupabaseDeliveryHistory,
)
from delivery.sender import SesEmailSender
from delivery.service import DeliveryService


async def run_ingestion(context: GraphContext) -> None:
    """Ingestion Graph 실행 및 저장 결과 출력"""

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


async def run_recommendation(
    context: GraphContext,
) -> tuple[dict[str, object], ...]:
    """Recommendation Graph를 실행하고 추천 후보를 출력한다."""

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

    recommendations = result.get("recommendations", ())
    print(f"최종 추천 수: {len(recommendations)}")
    return recommendations


def send_email(
    recommendations: tuple[dict[str, object], ...],
    delivery_history: DeliveryHistory,
) -> None:
    """추천 결과를 이메일로 전송한다."""

    # sender.py에서 타입체크 때문에 한번 cast
    ses_client = cast(
        "SESV2Client",
        boto3.client(
            "sesv2",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        ),
    )

    sender = SesEmailSender(
        ses_client=ses_client,
        sender_email=os.environ["SES_SENDER_EMAIL"],
    )

    delivery_service = DeliveryService(
        email_sender=sender,
        delivery_history=delivery_history,
    )

    delivery_service.send_recommendation_emails(
        {
            os.environ["RECIPIENT_EMAIL"]: recommendations,
        }
    )


async def main() -> None:
    load_dotenv()

    context = GraphContext(
        gemini_client=create_gemini_client(),
        supabase_client=create_supabase_client(),
    )

    delivery_history = SupabaseDeliveryHistory(
        client=context.supabase_client,
    )

    await run_ingestion(context)
    recommendations = await run_recommendation(context)
    send_email(
        recommendations=recommendations,
        delivery_history=delivery_history,
    )


if __name__ == "__main__":
    asyncio.run(main())
