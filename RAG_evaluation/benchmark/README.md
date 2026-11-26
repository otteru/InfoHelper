# 검색 결과 벤치마크 실행

프로젝트 루트에서 `infohelper` 환경을 활성화한 뒤 실행한다.

```bash
conda activate infohelper
python -m RAG_evaluation.benchmark.main bm25_kiwi_v1.jsonl
```

- `RAG_evaluation/artifacts/zighang_v1/runs/`에 평가할 검색 결과 JSONL을 준비하고, 명령의 파일명을 바꾼다. 인자는 경로 없이 `.jsonl` 파일명만 입력한다.
- 정답은 `RAG_evaluation/dataset/labeling/pool_v2/qrels.txt`, 쿼리는 `RAG_evaluation/dataset/queries/eval_queries_80.jsonl`을 사용한다.
- 실행하면 요약 지표가 터미널에 출력되고, `RAG_evaluation/artifacts/zighang_v1/benchmark_reports/pool_v2/<파일명에서 확장자를 뺀 이름>_<UTC 시각>/`에 `result.json`과 `report.md`가 저장된다.
