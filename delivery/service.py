from collections.abc import Mapping

from delivery.history import DeliveryHistory
from delivery.models import DeliveryKey, EmailMessage
from delivery.sender import EmailSender
from delivery.templates import (
    Recommendation,
    render_html_digest,
    render_text_digest,
)


def _get_notice_id(recommendation: Recommendation) -> str:
    """추천 결과에서 공지 ID를 검증해 반환한다."""
    notice_id = recommendation.get("notice_id")

    if not isinstance(notice_id, str) or not notice_id.strip():
        raise ValueError("추천 결과의 notice_id가 올바르지 않습니다.")

    return notice_id


class DeliveryService:
    def __init__(
        self,
        email_sender: EmailSender,
        delivery_history: DeliveryHistory,
    ) -> None:
        """이메일 전송기와 발송 이력 저장소를 주입받는다."""
        self._email_sender = email_sender
        self._delivery_history = delivery_history

    def send_recommendation_emails(
        self,
        recommendations_by_recipient: Mapping[
            str,
            tuple[Recommendation, ...],
        ],
    ) -> None:
        """여러 사용자의 추천을 중복 제거한 뒤 이메일로 전송한다."""
        candidates = tuple(
            DeliveryKey(
                recipient_email=recipient,
                notice_id=_get_notice_id(recommendation),
            )
            for recipient, recommendations
            in recommendations_by_recipient.items()
            for recommendation in recommendations
        )

        # 이미 저장된 즉 다시 안보내도 되는 pairs
        delivered_pairs = self._delivery_history.find_delivered_pairs(
            candidates
        )

        for recipient, recommendations in recommendations_by_recipient.items():
            selected_recommendations = tuple(
                recommendation
                for recommendation in recommendations
                if DeliveryKey(
                    recipient_email=recipient,
                    notice_id=_get_notice_id(recommendation),
                )
                not in delivered_pairs
            )

            if not selected_recommendations:
                continue

            message = EmailMessage(
                recipient=recipient,
                subject="[Info Helper] 오늘의 추천 공지",
                html_body=render_html_digest(selected_recommendations),
                text_body=render_text_digest(selected_recommendations),
            )

            # 실패하면 예외가 발생하므로 아래 이력 저장은 실행되지 않는다.
            self._email_sender.send(message)

            successful_deliveries = tuple(
                DeliveryKey(
                    recipient_email=recipient,
                    notice_id=_get_notice_id(recommendation),
                )
                for recommendation in selected_recommendations
            )

            self._delivery_history.save_delivered_pairs(
                successful_deliveries
            )
