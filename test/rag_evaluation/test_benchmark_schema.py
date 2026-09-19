"""벤치마크 예측 스키마가 Notion 예시와 단계 제약을 지키는지 검증한다."""

import pytest
from pydantic import ValidationError

from RAG_evaluation.benchmark.schema import QueryPrediction

NOTION_EXAMPLE = {
    'query_id': 'q001',
    'candidates': [
        {'doc_id': 'd31', 'score': 0.91, 'rank': 1},
        {'doc_id': 'd12', 'score': 0.89, 'rank': 2},
    ],
    'ranked': [
        {'doc_id': 'd12', 'score': 0.97, 'rank': 1},
        {'doc_id': 'd31', 'score': 0.83, 'rank': 2},
    ],
    'recommended': [{'doc_id': 'd12'}],
    'timing': {
        'embedding_ms': 25,
        'retrieval_ms': 71,
        'rerank_ms': 102,
        'total_ms': 198,
    },
    'cost': {'usd': 0.00018},
}


def test_노션_예시가_통과한다() -> None:
    """고도화(2)에 적어 둔 예측 JSON을 그대로 받는다."""
    prediction = QueryPrediction.model_validate(NOTION_EXAMPLE)
    assert prediction.query_id == 'q001'
    assert prediction.candidates[0].doc_id == 'd31'
    assert prediction.ranked[0].doc_id == 'd12'
    assert prediction.recommended is not None
    assert prediction.recommended[0].doc_id == 'd12'
    assert prediction.timing is not None
    assert prediction.timing.total_ms == 198
    assert prediction.cost is not None
    assert prediction.cost.usd == 0.00018


def test_없는_단계는_생략할_수_있다() -> None:
    """rerank·추천·계측 전에도 후보와 순위만으로 저장할 수 있다."""
    prediction = QueryPrediction.model_validate({
        'query_id': 'Q001',
        'candidates': [{'doc_id': 'd1', 'score': 0.5, 'rank': 1}],
        'ranked': [{'doc_id': 'd1', 'score': 0.5, 'rank': 1}],
    })
    assert prediction.recommended is None
    assert prediction.timing is None
    assert prediction.cost is None


def test_추천_공고는_순위에_있어야_한다() -> None:
    """ranked에 없는 공고를 recommended에 넣으면 실패한다."""
    payload = {
        'query_id': 'Q001',
        'candidates': [{'doc_id': 'd1', 'score': 0.5, 'rank': 1}],
        'ranked': [{'doc_id': 'd1', 'score': 0.5, 'rank': 1}],
        'recommended': [{'doc_id': 'd2'}],
    }
    with pytest.raises(ValidationError, match='ranked에 있어야'):
        QueryPrediction.model_validate(payload)


def test_추가_필드는_거부한다() -> None:
    """스키마에 없는 키는 예측 계약을 깨므로 실패한다."""
    payload = dict(NOTION_EXAMPLE)
    payload['extra'] = True
    with pytest.raises(ValidationError):
        QueryPrediction.model_validate(payload)
