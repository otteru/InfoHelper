# Python이 타입 힌트를 즉시 평가하지 않고 문자열 형태로 보관
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from delivery.models import EmailMessage

# docker 환경에서 boto3만 있을 수 있기에 타입 체킹 할 때만 확인하게
# 실제로 돌아가는데 필요한 것은 boto3만 있으면 됨
if TYPE_CHECKING:
    from mypy_boto3_sesv2.client import SESV2Client


class EmailSender(Protocol):
    """이메일 전송을 위해 구현체가 따라야 하는 인터페이스."""

    def send(self, message: EmailMessage) -> None:
        """이메일을 전송한다."""
        ...


class SesEmailSender:
    """AWS SES v2를 이용해서 이메일을 전송한다."""

    def __init__(
        self,
        ses_client: SESV2Client,
        sender_email: str,
    ) -> None:
        self._ses_client = ses_client
        self._sender_email = sender_email

    def send(self, message: EmailMessage) -> None:
        self._ses_client.send_email(
            FromEmailAddress=self._sender_email,
            Destination={
                "ToAddresses": [message.recipient],
            },
            Content={
                "Simple": {
                    "Subject": {
                        "Data": message.subject,
                        "Charset": "UTF-8",
                    },
                    "Body": {
                        "Html": {
                            "Data": message.html_body,
                            "Charset": "UTF-8",
                        },
                        "Text": {
                            "Data": message.text_body,
                            "Charset": "UTF-8",
                        },
                    },
                },
            },
        )
