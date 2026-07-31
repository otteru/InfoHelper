from dataclasses import dataclass


# slots=True는 인스턴스가 가질 수 있는 속성을 미리 고정하는 옵션
@dataclass(frozen=True, slots=True)
class EmailMessage:
    """이메일 한 통을 전송하는 데 필요한 데이터."""

    recipient: str
    subject: str
    html_body: str
    text_body: str
