# 검색 결과 출력 계약

`benchmark/schema/prediction.py`의 `QueryPrediction`을 사용한다.
JSONL 한 줄은 쿼리 하나이며 아래 예시는 가독성을 위해 펼쳤다.
수치는 형식 설명용이며 실제 측정 결과가 아니다.

## 공통 규칙

- `candidates`: 검색기 최종 top-k. Hybrid는 RRF 결합 후 top-k이다.
- `ranked`: 별도 reranker가 없으면 candidates와 같다. 각 목록의 rank는 1부터 연속이다.
- `recommended`: 미실행은 null, 판단 후 추천 없음은 빈 배열이다.
- `timing.kind`: total_ms가 실측이면 measured, 계산한 추정값이면 estimated이다.
  기존 파일에서 생략한 경우 null(방식 미상)이며 실측으로 간주하지 않는다.
- `query_encoding_ms`: 쿼리를 검색 표현으로 변환하는 시간이다. Dense는 임베딩·검증, BM25는 정규화·토큰화를 포함한다.
- `fusion_ms`: 결과 결합에 걸린 실측 시간이다. RRF는 reranker가 아니므로 rerank_ms와 구분한다.
- 실행하지 않거나 측정하지 않은 단계 시간은 null이다. 초기 파일 로딩, 문서 임베딩,
  전체 문서 토큰화·BM25 색인 생성, 결과 파일 저장은 쿼리 시간에서 제외한다.
- `cost.usd`는 해당 쿼리 검색에 필요한 API 비용이며
  서버·DB 등 인프라 비용은 제외한다. API 호출 없는 BM25는 0, 비용 미상은 cost=null이다.
- cost는 usd만 가지며 API 비용으로 해석한다.
  기존 산출물에 인프라 비용 등이 포함돼 있다면 이 계약으로 사용하기 전에 확인해야 한다.

## Dense

query_encoding_ms는 쿼리 임베딩, retrieval_ms는 DB 검색·결과 변환,
total_ms는 검색 함수 전체를 직접 측정한다. 전체 시간은 단계 합과 정확히 같을 필요가 없다.

```json
{
  "query_id": "Q001",
  "candidates": [{"doc_id": "d31", "score": 0.91, "rank": 1}],
  "ranked": [{"doc_id": "d31", "score": 0.91, "rank": 1}],
  "recommended": null,
  "timing": {
    "kind": "measured",
    "query_encoding_ms": 25,
    "retrieval_ms": 71,
    "fusion_ms": null,
    "rerank_ms": null,
    "total_ms": 97
  },
  "cost": {"usd": 0.00018}
}
```

## BM25

query_encoding_ms는 쿼리 정규화·토큰화, retrieval_ms는 점수 계산·정렬·top-k 선택을 포함한다.
total_ms는 검색 함수 전체를 직접 측정한다.

```json
{
  "query_id": "Q001",
  "candidates": [{"doc_id": "d31", "score": 8.2, "rank": 1}],
  "ranked": [{"doc_id": "d31", "score": 8.2, "rank": 1}],
  "recommended": null,
  "timing": {
    "kind": "measured",
    "query_encoding_ms": 3,
    "retrieval_ms": 10,
    "fusion_ms": null,
    "rerank_ms": null,
    "total_ms": 13
  },
  "cost": {"usd": 0}
}
```

## Hybrid (저장된 결과 사용)

같은 쿼리의 Dense·BM25를 동시에 시작한다고 가정한다.

- total_ms = max(Dense.total_ms, BM25.total_ms) + fusion_ms
- cost.usd = Dense.cost.usd + BM25.cost.usd
- 시간은 병렬 실행 추정치, 비용은 원본 검색을 각각 한 번 실행할 때의 API 비용이다.
  저장 결과 재사용 작업의 추가 과금액을 의미하지 않는다.
- 원본 total_ms가 하나라도 없으면 Hybrid total_ms=null이다.
  원본 cost가 하나라도 없으면 Hybrid cost=null이다. 시간과 비용은 독립적으로 처리한다.
- query_encoding_ms·retrieval_ms는 null로 둔다. 개별 검색 시간은 원본 결과에 남긴다.
- 쿼리별 total_ms를 구한 뒤 p50·p95를 계산한다. 검색기별 p95를 조합하지 않는다.

```json
{
  "query_id": "Q001",
  "candidates": [{"doc_id": "d31", "score": 0.03278688524590164, "rank": 1}],
  "ranked": [{"doc_id": "d31", "score": 0.03278688524590164, "rank": 1}],
  "recommended": null,
  "timing": {
    "kind": "estimated",
    "query_encoding_ms": null,
    "retrieval_ms": null,
    "fusion_ms": 2,
    "rerank_ms": null,
    "total_ms": 99
  },
  "cost": {"usd": 0.00018}
}
```

## 이번 단계의 적용 범위

Dense·BM25의 search_with_timing()은 query_encoding_ms와 retrieval_ms를 나누어 반환한다.
collect_results()가 쿼리별 QueryPrediction을 만들고 save_results()가
`runs/<run_name>.jsonl`에 timing과 함께 저장한다.
문서별 TREC run은 저장하지 않는다. Hybrid는 예측 파일의 candidates로 RRF하고
해시·쿼리·후보를 검증한 뒤 쿼리별 병렬 추정 시간과 원본 API 비용 합계를 저장한다.
보고서는 `latency_kind`로 실측·추정을 구분한다. Hybrid p95는 `estimated`로 읽는다.
