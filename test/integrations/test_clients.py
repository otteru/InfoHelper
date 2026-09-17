"""OpenRouter 클라이언트와 임베딩 변환을 검증한다."""

from types import SimpleNamespace

import pytest

from integrations import clients


def test_openrouter_키가_없으면_클라이언트_생성이_실패한다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OPENROUTER_API_KEY가 없으면 클라이언트 생성을 막는다."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        clients.create_openrouter_client()


def test_create_embedding이_벡터를_반환한다() -> None:
    """OpenRouter embeddings 응답에서 벡터 값을 꺼낸다."""
    fake_client = SimpleNamespace(
        embeddings=SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(
                data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])]
            )
        )
    )

    values = clients.create_embedding(fake_client, "hello")

    assert values == [0.1, 0.2, 0.3]


def test_create_embedding은_빈_결과를_거절한다() -> None:
    """임베딩 data가 없으면 오류를 낸다."""
    fake_client = SimpleNamespace(
        embeddings=SimpleNamespace(
            create=lambda **kwargs: SimpleNamespace(data=[])
        )
    )

    with pytest.raises(ValueError, match="임베딩 결과가 비어 있습니다"):
        clients.create_embedding(fake_client, "hello")
