"""시스템 지표가 실측과 추정 지연시간을 구분하는지 검증한다."""

import pytest

from RAG_evaluation.benchmark.evaluator import evaluate
from RAG_evaluation.benchmark.schema import QueryPrediction


def _prediction(
    query_id: str, *, kind: str | None = None, total_ms: float | None = None, usd: float | None = None,
) -> QueryPrediction:
    """한 공고 후보와 선택적 시간·비용을 가진 예측을 만든다."""
    hits = ({'doc_id': 'd1', 'rank': 1, 'score': 1.0},)
    payload: dict[str, object] = {'query_id': query_id, 'candidates': hits, 'ranked': hits}
    if kind is not None or total_ms is not None:
        payload['timing'] = {'kind': kind, 'total_ms': total_ms}
    if usd is not None:
        payload['cost'] = {'usd': usd}
    return QueryPrediction.model_validate(payload)


def _report(*predictions: QueryPrediction):
    """동일 쿼리 집합의 예측을 평가한다."""
    qrels = {item.query_id: {'d1': 2} for item in predictions}
    return evaluate(predictions, qrels, run_id='test', qrels_version='test')


def test_실측_지연시간만_집계한다() -> None:
    """kind=measured인 total_ms로 p95를 계산하고 측정 방식을 기록한다."""
    report = _report(_prediction('Q1', kind='measured', total_ms=10))
    assert report.system is not None
    assert report.system.p95_latency_ms == 10
    assert report.system.latency_kind == 'measured'
    assert report.system.latency_sample_count == 1


def test_추정_지연시간도_방식과_함께_집계한다() -> None:
    """kind=estimated인 Hybrid 추정값을 실측과 같은 칸에 섞지 않고 남긴다."""
    report = _report(_prediction('Q1', kind='estimated', total_ms=99))
    assert report.system is not None
    assert report.system.p95_latency_ms == 99
    assert report.system.latency_kind == 'estimated'
    assert report.system.latency_sample_count == 1


def test_방식_미상_시간은_지연시간에서_제외한다() -> None:
    """kind가 없는 total_ms는 실측으로 보지 않으며 비용은 따로 집계한다."""
    report = _report(_prediction('Q1', total_ms=10, usd=0.001))
    assert report.system is not None
    assert report.system.p95_latency_ms is None
    assert report.system.latency_kind is None
    assert report.system.latency_sample_count == 0
    assert report.system.mean_cost_usd_per_query == 0.001
    assert report.system.cost_sample_count == 1


def test_방식_미상과_실측이_섞이면_실측만_쓴다() -> None:
    """kind가 없는 시간은 무시하고 measured 표본만 집계한다."""
    report = _report(
        _prediction('Q1', kind='measured', total_ms=10),
        _prediction('Q2', total_ms=999),
    )
    assert report.system is not None
    assert report.system.p95_latency_ms == 10
    assert report.system.latency_kind == 'measured'
    assert report.system.latency_sample_count == 1


def test_실측과_추정을_한_보고서에서_거절한다() -> None:
    """서로 다른 산출 방식의 지연시간을 한 p95로 합치지 않는다."""
    with pytest.raises(ValueError, match='실측과 추정'):
        _report(
            _prediction('Q1', kind='measured', total_ms=10),
            _prediction('Q2', kind='estimated', total_ms=20),
        )


@pytest.mark.parametrize(('kind', 'total_ms', 'usd', 'label'), (
    ('measured', 10, None, '실측'),
    ('estimated', 99, None, '추정'),
    (None, 10, 0.001, '미측정'),
))
def test_보고서_시간_측정_방식을_표시한다(
    kind: str | None, total_ms: float, usd: float | None, label: str,
) -> None:
    """Markdown 요약의 지연시간 지표명에 산출 방식을 붙인다."""
    from RAG_evaluation.benchmark.report import render_markdown
    markdown = render_markdown(_report(_prediction('Q1', kind=kind, total_ms=total_ms, usd=usd)))
    assert f'| 시간 측정 방식 | {label} |' in markdown
    assert f'p95 latency (ms, {label})' in markdown
