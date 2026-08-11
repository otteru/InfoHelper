import pytest

from delivery.models import DeliveryKey, EmailMessage
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


class FakeDeliveryHistory:
    """발송 이력 조회·저장 요청을 기록하는 테스트 대역."""

    def __init__(
        self,
        delivered_pairs: frozenset[DeliveryKey] = frozenset(),
    ) -> None:
        self._delivered_pairs = delivered_pairs
        self.find_calls: tuple[tuple[DeliveryKey, ...], ...] = ()
        self.save_calls: tuple[tuple[DeliveryKey, ...], ...] = ()

    def find_delivered_pairs(
        self,
        candidates: tuple[DeliveryKey, ...],
    ) -> frozenset[DeliveryKey]:
        self.find_calls = (*self.find_calls, candidates)
        return frozenset(
            candidate
            for candidate in candidates
            if candidate in self._delivered_pairs
        )

    def save_delivered_pairs(
        self,
        deliveries: tuple[DeliveryKey, ...],
    ) -> None:
        self.save_calls = (*self.save_calls, deliveries)


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
    """미발송 추천을 전송하고 성공 이력을 저장한다."""
    fake_sender = FakeEmailSender()
    fake_history = FakeDeliveryHistory()
    service = DeliveryService(
        email_sender=fake_sender,
        delivery_history=fake_history,
    )
    recommendations = _recommendations()
    delivery_key = DeliveryKey(
        recipient_email="recipient@example.com",
        notice_id="notice-1",
    )

    service.send_recommendation_emails(
        {"recipient@example.com": recommendations}
    )

    assert fake_history.find_calls == ((delivery_key,),)
    assert fake_sender.messages == (
        EmailMessage(
            recipient="recipient@example.com",
            subject="[Info Helper] 오늘의 추천 공지",
            html_body=render_html_digest(recommendations),
            text_body=render_text_digest(recommendations),
        ),
    )
    assert fake_history.save_calls == ((delivery_key,),)


def test_delivery_service는_추천이_없으면_전송하지_않는다() -> None:
    """추천 결과가 없으면 빈 이메일도 보내지 않는다."""
    fake_sender = FakeEmailSender()
    fake_history = FakeDeliveryHistory()
    service = DeliveryService(
        email_sender=fake_sender,
        delivery_history=fake_history,
    )

    service.send_recommendation_emails(
        {"recipient@example.com": ()}
    )

    assert fake_sender.messages == ()
    assert fake_history.save_calls == ()


def test_delivery_service는_이미_발송한_추천을_제외한다() -> None:
    """사용자에게 이미 발송한 공지는 다시 전송하지 않는다."""
    delivery_key = DeliveryKey(
        recipient_email="recipient@example.com",
        notice_id="notice-1",
    )
    fake_sender = FakeEmailSender()
    fake_history = FakeDeliveryHistory(frozenset({delivery_key}))
    service = DeliveryService(
        email_sender=fake_sender,
        delivery_history=fake_history,
    )

    service.send_recommendation_emails(
        {"recipient@example.com": _recommendations()}
    )

    assert fake_history.find_calls == ((delivery_key,),)
    assert fake_sender.messages == ()
    assert fake_history.save_calls == ()


def test_delivery_service는_sender_오류를_호출자에게_전달한다() -> None:
    """전송 실패를 숨기지 않아 이후 발송 이력 저장을 막을 수 있게 한다."""
    fake_history = FakeDeliveryHistory()
    service = DeliveryService(
        email_sender=FailingEmailSender(),
        delivery_history=fake_history,
    )

    with pytest.raises(RuntimeError, match="이메일 전송 실패"):
        service.send_recommendation_emails(
            {"recipient@example.com": _recommendations()}
        )

    assert fake_history.save_calls == ()
