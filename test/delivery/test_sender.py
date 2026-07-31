from typing import cast

import pytest
from mypy_boto3_sesv2.client import SESV2Client

from delivery.models import EmailMessage
from delivery.sender import SesEmailSender


class FakeSesClient:
    """SES 요청을 저장하는 테스트 대역."""

    def __init__(self) -> None:
        self.calls: tuple[dict[str, object], ...] = ()

    def send_email(self, **kwargs: object) -> dict[str, str]:
        self.calls = (*self.calls, kwargs)
        return {"MessageId": "test-message-id"}


class FailingSesClient:
    """SES 전송 실패를 재현하는 테스트 대역."""

    def send_email(self, **kwargs: object) -> object:
        raise RuntimeError("SES 전송 실패")


def _create_message() -> EmailMessage:
    return EmailMessage(
        recipient="recipient@example.com",
        subject="[Info Helper] 오늘의 추천 공지",
        html_body="<h1>오늘의 추천 공지</h1>",
        text_body="오늘의 추천 공지",
    )


def test_ses_email_sender가_email_message를_ses_요청으로_변환한다() -> None:
    """EmailMessage의 모든 필드를 SES v2 요청 형식으로 전달한다."""
    fake_client = FakeSesClient()
    sender = SesEmailSender(
        ses_client=cast(SESV2Client, fake_client),
        sender_email="sender@example.com",
    )

    sender.send(_create_message())

    assert fake_client.calls == (
        {
            "FromEmailAddress": "sender@example.com",
            "Destination": {
                "ToAddresses": ["recipient@example.com"],
            },
            "Content": {
                "Simple": {
                    "Subject": {
                        "Data": "[Info Helper] 오늘의 추천 공지",
                        "Charset": "UTF-8",
                    },
                    "Body": {
                        "Html": {
                            "Data": "<h1>오늘의 추천 공지</h1>",
                            "Charset": "UTF-8",
                        },
                        "Text": {
                            "Data": "오늘의 추천 공지",
                            "Charset": "UTF-8",
                        },
                    },
                },
            },
        },
    )


def test_ses_email_sender는_ses_오류를_호출자에게_전달한다() -> None:
    """SES 오류를 숨기지 않아 발송 성공으로 잘못 처리하지 않게 한다."""
    sender = SesEmailSender(
        ses_client=cast(SESV2Client, FailingSesClient()),
        sender_email="sender@example.com",
    )

    with pytest.raises(RuntimeError, match="SES 전송 실패"):
        sender.send(_create_message())
