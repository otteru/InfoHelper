from typing import cast

import pytest
from supabase import Client

from delivery.history import SupabaseDeliveryHistory
from delivery.models import DeliveryKey


class FakeResponse:
    def __init__(self, data: object) -> None:
        self.data = data


class FakeRequest:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response

    def execute(self) -> FakeResponse:
        return self._response


class FakeTable:
    def __init__(self, client: "FakeSupabaseClient", name: str) -> None:
        self._client = client
        self._name = name

    def upsert(
        self,
        rows: list[dict[str, str]],
        *,
        on_conflict: str,
        ignore_duplicates: bool,
    ) -> FakeRequest:
        self._client.upsert_calls = (
            *self._client.upsert_calls,
            {
                "table": self._name,
                "rows": rows,
                "on_conflict": on_conflict,
                "ignore_duplicates": ignore_duplicates,
            },
        )
        return FakeRequest(FakeResponse([]))


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.rpc_calls: tuple[dict[str, object], ...] = ()
        self.upsert_calls: tuple[dict[str, object], ...] = ()
        self.rpc_response = FakeResponse([])

    def rpc(self, name: str, params: dict[str, object]) -> FakeRequest:
        self.rpc_calls = (
            *self.rpc_calls,
            {"name": name, "params": params},
        )
        return FakeRequest(self.rpc_response)

    def table(self, name: str) -> FakeTable:
        return FakeTable(self, name)


def test_find_delivered_pairs가_후보를_RPC로_한번에_조회한다() -> None:
    fake_client = FakeSupabaseClient()
    fake_client.rpc_response = FakeResponse(
        [
            {
                "recipient_email": "user-1@example.com",
                "notice_id": "notice-a",
                "channel": "email",
            }
        ]
    )
    history = SupabaseDeliveryHistory(cast(Client, fake_client))
    candidates = (
        DeliveryKey("user-1@example.com", "notice-a"),
        DeliveryKey("user-2@example.com", "notice-a"),
    )

    result = history.find_delivered_pairs(candidates)

    assert fake_client.rpc_calls == (
        {
            "name": "find_delivered_pairs",
            "params": {
                "p_candidates": [
                    {
                        "recipient_email": "user-1@example.com",
                        "notice_id": "notice-a",
                        "channel": "email",
                    },
                    {
                        "recipient_email": "user-2@example.com",
                        "notice_id": "notice-a",
                        "channel": "email",
                    },
                ]
            },
        },
    )
    assert result == frozenset(
        {DeliveryKey("user-1@example.com", "notice-a")}
    )


def test_save_delivered_pairs가_성공_이력을_중복_없이_저장한다() -> None:
    fake_client = FakeSupabaseClient()
    history = SupabaseDeliveryHistory(cast(Client, fake_client))

    history.save_delivered_pairs(
        (DeliveryKey("user-1@example.com", "notice-a"),)
    )

    assert fake_client.upsert_calls == (
        {
            "table": "recommendation_deliveries",
            "rows": [
                {
                    "recipient_email": "user-1@example.com",
                    "notice_id": "notice-a",
                    "channel": "email",
                }
            ],
            "on_conflict": "recipient_email,notice_id,channel",
            "ignore_duplicates": True,
        },
    )


def test_find_delivered_pairs는_RPC_응답이_배열이_아니면_실패한다() -> None:
    fake_client = FakeSupabaseClient()
    fake_client.rpc_response = FakeResponse(None)
    history = SupabaseDeliveryHistory(cast(Client, fake_client))

    with pytest.raises(ValueError, match="RPC 응답이 배열이 아닙니다"):
        history.find_delivered_pairs(
            (DeliveryKey("user-1@example.com", "notice-a"),)
        )


def test_find_delivered_pairs는_RPC_행의_필수값이_잘못되면_실패한다() -> None:
    fake_client = FakeSupabaseClient()
    fake_client.rpc_response = FakeResponse(
        [
            {
                "recipient_email": "user-1@example.com",
                "notice_id": "notice-a",
                "channel": None,
            }
        ]
    )
    history = SupabaseDeliveryHistory(cast(Client, fake_client))

    with pytest.raises(ValueError, match="channel이 올바르지 않습니다"):
        history.find_delivered_pairs(
            (DeliveryKey("user-1@example.com", "notice-a"),)
        )


def test_빈_발송_목록은_supabase를_호출하지_않는다() -> None:
    fake_client = FakeSupabaseClient()
    history = SupabaseDeliveryHistory(cast(Client, fake_client))

    assert history.find_delivered_pairs(()) == frozenset()
    history.save_delivered_pairs(())

    assert fake_client.rpc_calls == ()
    assert fake_client.upsert_calls == ()
