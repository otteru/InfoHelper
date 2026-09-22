"""벤치마크 예측 스키마가 Notion 예시와 단계 제약을 지키는지 검증한다."""

import json
from pathlib import Path
import re

import pytest
from pydantic import ValidationError

from RAG_evaluation.benchmark.schema import Cost, QueryPrediction, Timing

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
        'query_encoding_ms': 25,
        'retrieval_ms': 71,
        'rerank_ms': 102,
        'total_ms': 198,
    },
    'cost': {'usd': 0.00018},
}


def test_노션_예시가_통과한다() -> None:
    """고도화(2) 예시를 현재 출력 필드명으로 변환해 검증한다."""
    prediction = QueryPrediction.model_validate(NOTION_EXAMPLE)
    assert prediction.query_id == 'q001'
    assert prediction.candidates[0].doc_id == 'd31'
    assert prediction.ranked[0].doc_id == 'd12'
    assert prediction.recommended is not None
    assert prediction.recommended[0].doc_id == 'd12'
    assert prediction.timing is not None
    assert prediction.timing.total_ms == 198
    assert prediction.timing.kind is None
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


def test_출력_계약의_예시를_읽는다() -> None:
    """문서의 세 예시가 직렬화 가능하며 Hybrid 계산 기준을 만족한다."""
    path = Path(__file__).resolve().parents[2] / 'RAG_evaluation/retrieval/output-contract.md'
    examples = re.findall(r'```json\n(.*?)\n```', path.read_text(encoding='utf-8'), re.DOTALL)
    assert len(examples) == 3
    dense, bm25, hybrid = tuple(QueryPrediction.model_validate_json(value) for value in examples)
    for prediction in (dense, bm25, hybrid):
        assert QueryPrediction.model_validate_json(prediction.model_dump_json()) == prediction
        assert prediction.candidates == prediction.ranked
    assert dense.timing is not None and bm25.timing is not None and hybrid.timing is not None
    assert dense.timing.kind == bm25.timing.kind == 'measured'
    assert hybrid.timing.kind == 'estimated'
    assert hybrid.timing.total_ms == max(dense.timing.total_ms, bm25.timing.total_ms) + hybrid.timing.fusion_ms
    assert dense.cost is not None and bm25.cost is not None and hybrid.cost is not None
    assert hybrid.cost.usd == dense.cost.usd + bm25.cost.usd


@pytest.mark.parametrize('field', ('query_encoding_ms', 'retrieval_ms', 'fusion_ms', 'rerank_ms', 'total_ms'))
@pytest.mark.parametrize('value', (-1, float('inf'), float('-inf'), float('nan')))
def test_잘못된_시간을_거부한다(field: str, value: float) -> None:
    """단계별 시간에 음수나 비유한 값이 들어가는 것을 막는다."""
    with pytest.raises(ValidationError):
        Timing.model_validate({field: value})


def test_산출_방식과_비용_범위를_제한한다() -> None:
    """정의하지 않은 측정 방식과 인프라 비용 범위를 거부한다."""
    with pytest.raises(ValidationError):
        Timing.model_validate({'kind': 'parallel'})
    with pytest.raises(ValidationError):
        Cost.model_validate({'scope': 'infrastructure', 'usd': 1})


def test_미측정과_비용_없음을_구분한다() -> None:
    """부분 계측과 API 비용 0을 null과 구별해 보존한다."""
    prediction = QueryPrediction.model_validate({
        **NOTION_EXAMPLE,
        'timing': {'kind': 'estimated', 'fusion_ms': 2},
        'cost': {'usd': 0},
    })
    payload = json.loads(prediction.model_dump_json())
    assert payload['timing']['total_ms'] is None
    assert payload['timing']['fusion_ms'] == 2
    assert payload['cost']['usd'] == 0
