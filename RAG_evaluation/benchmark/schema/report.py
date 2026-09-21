"""단계별 평가 지표와 벤치마크 보고서 스키마."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Score = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class MetricModel(BaseModel):
    """평가 결과의 공통 불변 모델."""

    model_config = ConfigDict(frozen=True, extra='forbid')


class CandidateMetrics(MetricModel):
    """qrel >= 1 기준 후보 검색 품질."""

    recall_at_20: Score | None = Field(description='Primary: Recall@20')
    success_at_20: Score | None = Field(description='Secondary: Success@20')


class RankingMetrics(MetricModel):
    """nDCG는 0·1·2점, Precision과 MRR은 qrel >= 1 기준 순위 품질."""

    ndcg_at_5: Score | None = Field(description='Primary: nDCG@5')
    precision_at_5: Score | None = Field(description='Secondary: Precision@5')
    mrr_at_5: Score | None = Field(description='Secondary: MRR@5')


class RecommendationMetrics(MetricModel):
    """qrel == 2 기준 추천 품질과 별도 검증된 negative query의 정확도."""

    precision: Score | None = Field(description='Primary: 추천 Precision')
    recall: Score | None = Field(description='Secondary: 추천 Recall')
    negative_query_accuracy: Score | None = Field(description='Secondary: 미추천 정확도')
    negative_query_count: int = Field(ge=0)


class SystemMetrics(MetricModel):
    """한 산출 방식의 total_ms와 API 비용을 집계한 검색 지연시간."""

    p95_latency_ms: NonNegative | None = Field(description='Primary: end-to-end retrieval p95(ms)')
    p50_latency_ms: NonNegative | None = Field(description='Secondary: end-to-end retrieval p50(ms)')
    mean_cost_usd_per_query: NonNegative | None = Field(description='Secondary: 쿼리당 평균 비용(USD)')
    latency_sample_count: int = Field(ge=0)
    latency_kind: Literal['measured', 'estimated'] | None = Field(
        default=None, description='p50·p95에 사용한 total_ms 산출 방식. 표본이 없으면 null.',
    )
    cost_sample_count: int = Field(ge=0)


class QueryMetrics(MetricModel):
    """실패 분석을 위한 쿼리별 검색 평가 결과."""

    query_id: str = Field(min_length=1)
    candidate: CandidateMetrics
    ranking: RankingMetrics


class BenchmarkReport(MetricModel):
    """보고서에 전달할 전체 집계와 쿼리별 결과이며 미측정 지표는 None이다."""

    run_id: str = Field(min_length=1)
    qrels_version: str = Field(min_length=1)
    query_count: int = Field(ge=0)
    candidate: CandidateMetrics
    ranking: RankingMetrics
    recommendation: RecommendationMetrics | None = None
    system: SystemMetrics | None = None
    per_query: tuple[QueryMetrics, ...]
