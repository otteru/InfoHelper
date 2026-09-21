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


@pytest.mark.parametrize('cost', (0.00001, 0, None))
def test_임베딩_응답의_비용을_반환한다(cost: float | None) -> None:
    """실제 OpenAI SDK 응답 모델의 확장 cost 필드와 미제공을 처리한다."""
    from openai.types import CreateEmbeddingResponse
    from unittest.mock import Mock

    usage = {'prompt_tokens': 2, 'total_tokens': 2, **({'cost': cost} if cost is not None else {})}
    response = CreateEmbeddingResponse.model_validate({
        'object': 'list', 'model': 'test',
        'data': [{'object': 'embedding', 'index': 0, 'embedding': [0.1, 0.2]}],
        'usage': usage,
    })
    client = Mock()
    client.embeddings.create.return_value = response
    assert clients.create_embedding_with_cost(client, 'hello') == ([0.1, 0.2], cost)
    client.embeddings.create.assert_called_once()


@pytest.mark.parametrize('cost', (-1, float('inf'), float('nan'), True, '0.01'))
def test_잘못된_API_비용을_거절한다(cost: object) -> None:
    """음수·비유한 값·숫자가 아닌 비용을 실제 과금액으로 기록하지 않는다."""
    from unittest.mock import Mock

    client = Mock()
    client.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.1, 0.2])], usage=SimpleNamespace(cost=cost),
    )
    with pytest.raises(ValueError, match='비용'):
        clients.create_embedding_with_cost(client, 'hello')
