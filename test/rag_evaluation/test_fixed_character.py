"""평가 임베딩의 입력 호환성과 실패·재개 동작을 검증한다."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from RAG_evaluation.embedding import fixed_character as fc
from integrations.clients import create_embedding


@pytest.fixture
def corpus(tmp_path: Path) -> fc.Corpus:
    """두 청크를 생성하는 한글 공고 파일을 준비한다."""
    path = tmp_path / 'corpus.jsonl'
    path.write_text(json.dumps({
        'id': '9b46bffb-8536-475c-9196-ba87ac33d5b6', 'title': '개발자',
        'content': '가' * 1000 + '나' * 50, 'url': 'https://example.com/job', 'metadata': {},
    }, ensure_ascii=False) + '\n', encoding='utf-8')
    result = fc.load_corpus(path)
    assert result.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def test_기존_청킹과_제목_입력_형식(corpus: fc.Corpus) -> None:
    """한글 문자 경계와 제목을 붙이는 기존 입력 형식을 유지한다."""
    assert tuple(chunk.content for chunk in corpus.chunks) == ('가' * 1000, '나' * 50)
    assert corpus.chunks[1].embedding_input == 'title: 개발자 | text: ' + '나' * 50
    assert fc.split_text(' ' * 1000 + '나') == ('나',)


@pytest.mark.parametrize('vectors', [[1.0], [0.0, 0.0], [float('nan'), 1.0], [float('inf'), 1.0]])
def test_잘못된_벡터_거절(vectors: list[float]) -> None:
    """차원 불일치·영벡터·비유한 벡터의 저장을 차단한다."""
    with pytest.raises(ValueError):
        fc.validate_embedding(vectors, 2)


def test_배치_응답_역순_복원(corpus: fc.Corpus) -> None:
    """API 응답 순서가 뒤집혀도 공고와 벡터를 올바르게 연결한다."""
    client = Mock()
    client.embeddings.create.return_value.data = [
        SimpleNamespace(index=1, embedding=[0.0, 1.0]),
        SimpleNamespace(index=0, embedding=[1.0, 0.0]),
    ]
    assert fc.embed_batch(client, corpus.chunks, 'model', 2) == ([1.0, 0.0], [0.0, 1.0])


def test_공통_클라이언트_옵션_전달() -> None:
    """실험 모델과 차원이 실제 API 인자로 전달되는지 확인한다."""
    client = Mock()
    client.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(embedding=[1.0, 0.0])], usage=None,
    )
    create_embedding(client, 'input', model='test-model', dimensions=2)
    client.embeddings.create.assert_called_once_with(model='test-model', input='input', dimensions=2)


def test_설정_변경시_기존_run_재사용_거절(corpus: fc.Corpus) -> None:
    """같은 이름의 run을 다른 차원 설정으로 덮어쓰지 않는다."""
    payload = fc.run_payload(corpus, 'test', 'v1', 'model', 2)
    db = Mock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {**payload, 'dimensions': 3},
    ]
    with pytest.raises(ValueError, match='기존 run 설정'):
        fc.ensure_run(db, payload)


def test_저장된_청크는_재개시_호출하지_않음(corpus: fc.Corpus) -> None:
    """실패 후 재개할 때 누락 청크만 임베딩하고 완료 처리한다."""
    payload = fc.run_payload(corpus, 'test', 'v1', 'model', 2)
    db, client = Mock(), Mock()
    first, second = ((chunk.doc_id, chunk.chunk_index) for chunk in corpus.chunks)
    with (
        patch.object(fc, 'ensure_run', return_value={'run_id': 'run', 'status': 'failed'}),
        patch.object(fc, 'save_documents'),
        patch.object(fc, 'saved_chunk_keys', side_effect=[frozenset({first}), frozenset({first, second})]),
        patch.object(fc, 'embed_batch', return_value=([1.0, 0.0],)) as embed,
    ):
        result = fc.execute_run(db, client, corpus, payload)
    embed.assert_called_once_with(client, (corpus.chunks[1],), 'model', 2)
    assert result['new_embeddings'] == 1
    assert result['status'] == 'completed'


def test_임베딩_실패시_failed_저장(corpus: fc.Corpus) -> None:
    """외부 API 실패가 완료 상태로 기록되지 않게 한다."""
    payload = fc.run_payload(corpus, 'test', 'v1', 'model', 2)
    db = Mock()
    with (
        patch.object(fc, 'ensure_run', return_value={'run_id': 'run', 'status': 'pending'}),
        patch.object(fc, 'save_documents'),
        patch.object(fc, 'saved_chunk_keys', return_value=frozenset()),
        patch.object(fc, 'embed_batch', side_effect=RuntimeError('API 실패')),
        pytest.raises(RuntimeError, match='API 실패'),
    ):
        fc.execute_run(db, Mock(), corpus, payload)
    db.table.return_value.update.assert_called_with({'status': 'failed'})


def test_실패_상태_저장도_실패하면_원래_오류_유지(corpus: fc.Corpus) -> None:
    """DB 연결 장애가 원래 임베딩 오류를 덮어쓰지 않게 한다."""
    payload = fc.run_payload(corpus, 'test', 'v1', 'model', 2)
    db = Mock()
    db.table.return_value.update.side_effect = [Mock(), RuntimeError('DB 실패')]
    with (
        patch.object(fc, 'ensure_run', return_value={'run_id': 'run', 'status': 'pending'}),
        patch.object(fc, 'save_documents'),
        patch.object(fc, 'saved_chunk_keys', return_value=frozenset()),
        patch.object(fc, 'embed_batch', side_effect=RuntimeError('API 실패')),
        pytest.raises(RuntimeError, match='API 실패'),
    ):
        fc.execute_run(db, Mock(), corpus, payload)


def test_페이지_제한보다_많은_결과_조회() -> None:
    """500행 이후의 저장된 청크도 읽어 재임베딩을 방지한다."""
    db = Mock()
    db.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.side_effect = [
        SimpleNamespace(data=[{'id': i} for i in range(500)]),
        SimpleNamespace(data=[{'id': 500}]),
    ]
    assert len(fc.select_rows(db, 'table', 'run_id', 'run', '*', 'id')) == 501
