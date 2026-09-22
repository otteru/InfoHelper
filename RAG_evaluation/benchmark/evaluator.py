"""쿼리별 지표를 계산하고 None을 제외한 macro 평균으로 보고서를 구성한다."""

from collections.abc import Iterable, Mapping, Sequence
from statistics import fmean
from typing import Literal

from RAG_evaluation.benchmark import metrics
from RAG_evaluation.benchmark.schema import (
    BenchmarkReport, CandidateMetrics, QueryMetrics, QueryPrediction,
    RankingMetrics, RecommendationMetrics, SystemMetrics,
)


def _mean(values: Iterable[float | None]) -> float | None:
    """정의된 점수만 평균하며 유효한 점수가 없으면 None을 반환한다."""
    valid = tuple(value for value in values if value is not None)
    return fmean(valid) if valid else None


def _evaluate_query(prediction: QueryPrediction, qrels: Mapping[str, int]) -> QueryMetrics:
    """한 쿼리의 후보와 최종 순위에 각 검색 지표를 적용한다."""
    candidates = tuple(hit.doc_id for hit in prediction.candidates)
    ranked = tuple(hit.doc_id for hit in prediction.ranked)
    return QueryMetrics(
        query_id=prediction.query_id,
        candidate=CandidateMetrics(
            recall_at_20=metrics.recall_at_k(candidates, qrels, 20),
            success_at_20=metrics.success_at_k(candidates, qrels, 20),
        ),
        ranking=RankingMetrics(
            ndcg_at_5=metrics.ndcg_at_k(ranked, qrels, 5),
            precision_at_5=metrics.precision_at_k(ranked, qrels, 5),
            mrr_at_5=metrics.mrr_at_k(ranked, qrels, 5),
        ),
    )


def _evaluate_recommendations(
    predictions: Sequence[QueryPrediction],
    qrels: Mapping[str, Mapping[str, int]],
    negative_query_ids: frozenset[str],
) -> RecommendationMetrics | None:
    """추천 단계를 실행한 쿼리만 집계하고 명시된 negative query를 평가한다."""
    executed = tuple(
        (prediction.query_id, tuple(doc.doc_id for doc in prediction.recommended))
        for prediction in predictions if prediction.recommended is not None
    )
    if not executed:
        return None
    negatives = tuple(docs for query_id, docs in executed if query_id in negative_query_ids)
    return RecommendationMetrics(
        precision=_mean(metrics.recommendation_precision(docs, qrels[query_id]) for query_id, docs in executed),
        recall=_mean(metrics.recommendation_recall(docs, qrels[query_id]) for query_id, docs in executed),
        negative_query_accuracy=metrics.negative_query_accuracy(negatives),
        negative_query_count=len(negatives),
    )


def _latency_samples(
    predictions: Sequence[QueryPrediction],
) -> tuple[tuple[float, ...], Literal['measured', 'estimated'] | None]:
    """kind가 있는 total_ms만 모으고 실측과 추정이 섞이면 거절한다."""
    measured = tuple(
        prediction.timing.total_ms for prediction in predictions
        if prediction.timing is not None
        and prediction.timing.kind == 'measured'
        and prediction.timing.total_ms is not None
    )
    
    estimated = tuple(
        prediction.timing.total_ms for prediction in predictions
        if prediction.timing is not None
        and prediction.timing.kind == 'estimated'
        and prediction.timing.total_ms is not None
    )
    
    if measured and estimated:
        raise ValueError('실측과 추정 지연시간을 한 보고서에서 섞을 수 없습니다')
    if measured:
        return measured, 'measured'
    if estimated:
        return estimated, 'estimated'
    return (), None


def _evaluate_system(predictions: Sequence[QueryPrediction]) -> SystemMetrics | None:
    """같은 kind의 total_ms와 비용이 있는 쿼리만 모아 성능 지표를 계산한다."""
    latencies, latency_kind = _latency_samples(predictions)
    costs = tuple(prediction.cost.usd for prediction in predictions if prediction.cost is not None)
    if not latencies and not costs:
        return None
    return SystemMetrics(
        p95_latency_ms=metrics.latency_percentile(latencies, 95),
        p50_latency_ms=metrics.latency_percentile(latencies, 50),
        mean_cost_usd_per_query=metrics.mean_cost_per_query(costs),
        latency_sample_count=len(latencies),
        latency_kind=latency_kind,
        cost_sample_count=len(costs),
    )


def evaluate(
    predictions: Sequence[QueryPrediction],
    qrels: Mapping[str, Mapping[str, int]],
    *,
    run_id: str,
    qrels_version: str,
    negative_query_ids: frozenset[str] = frozenset(),
) -> BenchmarkReport:
    """쿼리별 qrels와 예측을 평가해 집계 및 상세 결과를 반환한다."""
    query_ids = frozenset(prediction.query_id for prediction in predictions)
    if not predictions or len(query_ids) != len(predictions):
        raise ValueError('예측이 비어 있거나 query_id가 중복됩니다')
    if query_ids != qrels.keys():
        raise ValueError('예측과 qrels의 쿼리 집합이 일치해야 합니다')
    if not negative_query_ids <= query_ids:
        raise ValueError('negative query는 평가 대상 쿼리에 포함되어야 합니다')
    if any(grade != 0 for query_id in negative_query_ids for grade in qrels[query_id].values()):
        raise ValueError('negative query의 정답 점수는 모두 0이어야 합니다')

    # 여기서 query별 Candidate Retrieval, Ranking 스테이지 처리
    per_query = tuple(_evaluate_query(prediction, qrels[prediction.query_id]) for prediction in predictions)
    return BenchmarkReport(
        run_id=run_id,
        qrels_version=qrels_version,
        query_count=len(predictions),
        candidate=CandidateMetrics(
            recall_at_20=_mean(item.candidate.recall_at_20 for item in per_query),
            success_at_20=_mean(item.candidate.success_at_20 for item in per_query),
        ),
        ranking=RankingMetrics(
            ndcg_at_5=_mean(item.ranking.ndcg_at_5 for item in per_query),
            precision_at_5=_mean(item.ranking.precision_at_5 for item in per_query),
            mrr_at_5=_mean(item.ranking.mrr_at_5 for item in per_query),
        ),
        recommendation=_evaluate_recommendations(predictions, qrels, negative_query_ids),
        system=_evaluate_system(predictions),
        per_query=per_query,
    )
