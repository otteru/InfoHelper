from delivery.models import EmailMessage
from delivery.sender import EmailSender
from delivery.templates import (
    Recommendation,
    render_html_digest,
    render_text_digest,
)


class DeliveryService:
    def __init__(self, email_sender: EmailSender) -> None:
        self._email_sender = email_sender

    def send_recommendation_email(
        self,
        recipient: str,
        recommendations: tuple[Recommendation, ...],
    ) -> None:
        """추천 결과를 이메일로 조립해 전송한다."""
        if not recommendations:
            return

        message = EmailMessage(
            recipient=recipient,
            subject="[Info Helper] 오늘의 추천 공지",
            html_body=render_html_digest(recommendations),
            text_body=render_text_digest(recommendations),
        )

        self._email_sender.send(message)
