import pytest

from delivery.models import EmailMessage
from delivery.service import DeliveryService
from delivery.templates import render_html_digest, render_text_digest


class FakeEmailSender:
    """전송 요청을 저장하는 EmailSender 테스트 대역."""

    def __init__(self) -> None:
        self.messages: tuple[EmailMessage, ...] = ()

    def send(self, message: EmailMessage) -> None:
        self.messages = (*self.messages, message)


class FailingEmailSender:
    """이메일 전송 실패를 재현하는 테스트 대역."""

    def send(self, message: EmailMessage) -> None:
        raise RuntimeError("이메일 전송 실패")


def _recommendations() -> tuple[dict[str, object], ...]:
    return (
        {
            "notice_id": "notice-1",
            "title": "AI 해커톤 참가자 모집",
            "url": "https://example.com/notices/1",
            "best_chunk": "AI 서비스를 개발하는 해커톤입니다.",
            "matched_queries": ("AI 관련 프로그램",),
            "total_score": 0.9,
        },
    )


def test_delivery_service가_추천_이메일을_조립해_전송한다() -> None:
    """추천 결과로 EmailMessage를 만들고 Sender에 한 번 전달한다."""
    fake_sender = FakeEmailSender()
    service = DeliveryService(email_sender=fake_sender)
    recommendations = _recommendations()

    service.send_recommendation_email(
        recipient="recipient@example.com",
        recommendations=recommendations,
    )

    assert fake_sender.messages == (
        EmailMessage(
            recipient="recipient@example.com",
            subject="[Info Helper] 오늘의 추천 공지",
            html_body=render_html_digest(recommendations),
            text_body=render_text_digest(recommendations),
        ),
    )


def test_delivery_service는_추천이_없으면_전송하지_않는다() -> None:
    """추천 결과가 없으면 빈 이메일도 보내지 않는다."""
    fake_sender = FakeEmailSender()
    service = DeliveryService(email_sender=fake_sender)

    service.send_recommendation_email(
        recipient="recipient@example.com",
        recommendations=(),
    )

    assert fake_sender.messages == ()


def test_delivery_service는_sender_오류를_호출자에게_전달한다() -> None:
    """전송 실패를 숨기지 않아 이후 발송 이력 저장을 막을 수 있게 한다."""
    service = DeliveryService(email_sender=FailingEmailSender())

    with pytest.raises(RuntimeError, match="이메일 전송 실패"):
        service.send_recommendation_email(
            recipient="recipient@example.com",
            recommendations=_recommendations(),
        )
