from typing import Protocol

from supabase import Client

from delivery.models import DeliveryKey


def _parse_delivery_key(row: object) -> DeliveryKey:
    """Supabase RPC의 JSON 행을 DeliveryKey로 변환한다."""
    if not isinstance(row, dict):
        raise ValueError("발송 이력 RPC의 행 형식이 올바르지 않습니다.")

    recipient_email = row.get("recipient_email")
    notice_id = row.get("notice_id")
    channel = row.get("channel")

    if not isinstance(recipient_email, str):
        raise ValueError("recipient_email이 올바르지 않습니다.")

    if not isinstance(notice_id, str):
        raise ValueError("notice_id가 올바르지 않습니다.")

    if not isinstance(channel, str):
        raise ValueError("channel이 올바르지 않습니다.")

    return DeliveryKey(
        recipient_email=recipient_email,
        notice_id=notice_id,
        channel=channel,
    )


class DeliveryHistory(Protocol):
    def find_delivered_pairs(
        self,
        candidates: tuple[DeliveryKey, ...],
    ) -> frozenset[DeliveryKey]:
        """후보 중 이미 발송된 사용자·공지 쌍을 조회한다."""
        ...

    def save_delivered_pairs(
        self,
        deliveries: tuple[DeliveryKey, ...],
    ) -> None:
        """발송에 성공한 사용자·공지 쌍을 저장한다."""
        ...


class SupabaseDeliveryHistory:
    def __init__(self, client: Client) -> None:
        """발송 이력을 조회·저장할 Supabase 클라이언트를 받는다."""
        self._client = client

    def find_delivered_pairs(
        self,
        candidates: tuple[DeliveryKey, ...],
    ) -> frozenset[DeliveryKey]:
        """발송 후보 중 이미 발송 이력이 있는 쌍을 일괄 조회한다."""
        # candidate가 누구한테 어떤 공지를 보낼지 정리해놓은 것
        if not candidates:
            return frozenset()

        payload = tuple(
            {
                "recipient_email": candidate.recipient_email,
                "notice_id": candidate.notice_id,
                "channel": candidate.channel,
            }
            for candidate in candidates
        )

        response = self._client.rpc(
            "find_delivered_pairs",
            {"p_candidates": list(payload)},
        ).execute()

        # response.data의 범위가 너무 넓어서 pylance 에러를 처리하기 위한 코드
        data = response.data
        if not isinstance(data, list):
            raise ValueError("발송 이력 RPC 응답이 배열이 아닙니다.")

        return frozenset(
            _parse_delivery_key(row)
            for row in data
        )

    def save_delivered_pairs(
        self,
        deliveries: tuple[DeliveryKey, ...],
    ) -> None:
        """SES 발송에 성공한 사용자·공지 쌍을 중복 없이 저장한다."""
        if not deliveries:
            return

        rows = tuple(
            {
                "recipient_email": delivery.recipient_email,
                "notice_id": delivery.notice_id,
                "channel": delivery.channel,
            }
            for delivery in deliveries
        )

        (
            self._client.table("recommendation_deliveries")
            .upsert(
                list(rows),
                on_conflict="recipient_email,notice_id,channel",
                ignore_duplicates=True,
            )
            .execute()
        )
