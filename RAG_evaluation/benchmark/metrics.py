"""평가 지표 순수 함수: 순위순 문서 ID와 한 쿼리의 qrels를 입력받는다.

미평가 문서는 0점으로 간주하지 않고 오류로 알린다. Precision@k의 분모는
반환 개수와 관계없이 k이며, nDCG gain은 2**grade - 1을 사용한다.
쿼리별 결과의 집계와 None 처리 정책은 evaluator에서 결정한다.
"""

from collections.abc import Mapping, Sequence
from math import ceil, floor, isfinite, log2
from statistics import fmean


def _validate_results(doc_ids: Sequence[str], qrels: Mapping[str, int]) -> None:
    """중복 문서·잘못된 라벨·미평가 문서가 계산에 섞이는 것을 막는다."""
    if len(set(doc_ids)) != len(doc_ids):
        raise ValueError('문서 ID가 중복됩니다')
    if any(type(grade) is not int or grade not in (0, 1, 2) for grade in qrels.values()):
        raise ValueError('qrels 점수는 정수 0·1·2여야 합니다')
    if any(doc_id not in qrels for doc_id in doc_ids):
        raise ValueError('미평가 문서가 포함되어 있습니다')


def _top_k(doc_ids: Sequence[str], qrels: Mapping[str, int], k: int) -> Sequence[str]:
    """입력을 검증하고 순위순 상위 k개 문서를 반환한다."""
    if type(k) is not int or k < 1:
        raise ValueError('k는 양의 정수여야 합니다')
    _validate_results(doc_ids, qrels)
    return doc_ids[:k]


def recall_at_k(doc_ids: Sequence[str], qrels: Mapping[str, int], k: int = 20) -> float | None:
    """qrel >= 1인 전체 정답 중 상위 k개가 찾은 비율을 계산한다.
    (labeling 점수가 1 이상이면 relevant 한 것으로 평가)"""
    hits = _top_k(doc_ids, qrels, k)
    relevant_count = sum(grade >= 1 for grade in qrels.values())
    return sum(qrels[doc_id] >= 1 for doc_id in hits) / relevant_count if relevant_count else None


def success_at_k(doc_ids: Sequence[str], qrels: Mapping[str, int], k: int = 20) -> float:
    """상위 k개에 qrel >= 1인 문서가 하나라도 있으면 1을 반환한다."""
    return float(any(qrels[doc_id] >= 1 for doc_id in _top_k(doc_ids, qrels, k)))


def ndcg_at_k(doc_ids: Sequence[str], qrels: Mapping[str, int], k: int = 5) -> float | None:
    """0·1·2점의 지수 gain을 사용해 상위 k개의 DCG를 이상적 DCG로 나눈다."""
    hits = _top_k(doc_ids, qrels, k)
    # 각 자리 기여 = 관련도 / 순위
    dcg = sum((2 ** qrels[doc_id] - 1) / log2(rank + 1) for rank, doc_id in enumerate(hits, 1))
    # 이상적인 순위일 때의 DCG
    ideal = sum((2 ** grade - 1) / log2(rank + 1)
                for rank, grade in enumerate(sorted(qrels.values(), reverse=True)[:k], 1))
    return dcg / ideal if ideal else None

def precision_at_k(doc_ids: Sequence[str], qrels: Mapping[str, int], k: int = 5) -> float:
    """상위 k개 중 qrel >= 1인 문서 수를 고정 분모 k로 나눈다."""
    return sum(qrels[doc_id] >= 1 for doc_id in _top_k(doc_ids, qrels, k)) / k

def mrr_at_k(doc_ids: Sequence[str], qrels: Mapping[str, int], k: int = 5) -> float:
    """한 쿼리의 상위 k개에서 첫 관련 문서의 역순위를 반환한다."""
    hits = _top_k(doc_ids, qrels, k)
    return next((1.0 / rank for rank, doc_id in enumerate(hits, 1) if qrels[doc_id] >= 1), 0.0)


def recommendation_precision(doc_ids: Sequence[str], qrels: Mapping[str, int]) -> float | None:
    """추천한 문서 중 qrel == 2인 비율을 계산하며 추천이 없으면 None을 반환한다."""
    _validate_results(doc_ids, qrels)
    return sum(qrels[doc_id] == 2 for doc_id in doc_ids) / len(doc_ids) if doc_ids else None


def recommendation_recall(doc_ids: Sequence[str], qrels: Mapping[str, int]) -> float | None:
    """전체 qrel == 2 문서 중 추천한 비율을 계산한다."""
    _validate_results(doc_ids, qrels)
    positive_count = sum(grade == 2 for grade in qrels.values())
    return sum(qrels[doc_id] == 2 for doc_id in doc_ids) / positive_count if positive_count else None


def negative_query_accuracy(recommendations: Sequence[Sequence[str]]) -> float | None:
    """별도 검증된 negative query들의 추천 결과 중 빈 결과의 비율을 계산한다."""
    # recommendatoins의 쿼리들이 모두 nagative query여야 한다.
    return sum(not docs for docs in recommendations) / len(recommendations) if recommendations else None


def _validate_samples(values: Sequence[float]) -> None:
    """시간·비용 표본이 유한한 0 이상의 값인지 검사한다."""
    if any(not isfinite(value) or value < 0 for value in values):
        raise ValueError('측정값은 유한한 0 이상의 수여야 합니다')


def latency_percentile(latencies_ms: Sequence[float], percentile: float) -> float | None:
    """정렬된 실측 시간의 (n-1)*p 위치를 선형 보간해 백분위수를 계산한다."""
    if not isfinite(percentile) or not 0 <= percentile <= 100:
        raise ValueError('백분위는 0~100이어야 합니다')
    _validate_samples(latencies_ms)
    if not latencies_ms:
        return None
    ordered = sorted(latencies_ms)
    position = (len(ordered) - 1) * percentile / 100
    lower, upper = floor(position), ceil(position)
    # position이 정수가 아니면 그 사이 값을 계산해서 반환 해줌
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def mean_cost_per_query(costs_usd: Sequence[float]) -> float | None:
    """측정된 쿼리별 USD 비용의 평균을 계산한다."""
    _validate_samples(costs_usd)
    # fmean == sum(x)/len(x)
    return fmean(costs_usd) if costs_usd else None
