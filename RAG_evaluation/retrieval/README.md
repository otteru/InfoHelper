# 풀링용 검색 결과 생성

프로젝트 루트에서 Miniconda `infohelper` 환경을 사용한다.

```bash
conda activate infohelper
python -m pip install -e '.[evaluation]'
supabase migration up --local

python RAG_evaluation/retrieval/dense.py
python RAG_evaluation/retrieval/lexical.py
```

기본 입력은 정제된 `dataset/zighang/corpus.jsonl`과
`dataset/zighang/queries/eval_queries_80.jsonl`이다. `--corpus`, `--queries`,
`--corpus-version`, `--run-name`, `--top-k`, `--output-dir`로 변경할 수 있다.
검색에는 쿼리 파일의 `query`만 사용하며 `intent`, `notes`, `seed_hints`는 사용하지 않는다.

## Dense

- `fixed1000_qwen1536_v1`이라는 완료된 embedding run을 조회한다.
- corpus의 버전·파일 해시·문서 수와 DB의 실제 문서·청크 수를 검증한다.
- 기존 InfoHelper와 동일한 `text: {query}` 형식으로 Qwen 1,536차원 임베딩을 생성한다.
- `match_eval_documents` RPC에서 지정된 run만 코사인 유사도로 정확 검색한다.
- 같은 공고의 청크 중 가장 높은 점수를 공고 점수로 사용해 서로 다른 공고 top 20을 반환한다.
- 풀링 후보 수집이므로 유사도 임계값이나 운영 추천 점수 공식을 적용하지 않는다.
- `.env`를 읽은 뒤 기본 `.env.local`이 덮어쓴다. 다른 대상은 `--env-file`로 명시한다.
- 다른 임베딩 실험은 `--embedding-run-name`과 새 `--run-name`을 함께 지정한다.

run의 모델·차원·query_template을 읽으므로 설정을 검색 코드에 중복으로 고정하지 않는다.
기존 운영 검색과 달리 평가 검색은 공고 단위이며 HNSW 근사 검색을 사용하지 않는다.

## BM25

- 동일 corpus의 `제목 + 줄바꿈 + 전체 본문`을 공고 단위로 색인한다.
- Kiwi 0.22의 `cong` 모델로 문서와 쿼리를 동일하게 토큰화한다.
- NFKC 정규화와 casefold를 적용하고 문자·숫자가 없는 토큰만 제외한다.
- 별도 불용어·사전·metadata 필터는 적용하지 않는다.
- `rank-bm25`의 `BM25Okapi`를 사용하며 기본값은 `k1=1.5`, `b=0.75`, `epsilon=0.25`다.
- `--k1`, `--b`, `--epsilon`으로 파라미터를 변경할 수 있다.
- 임베딩 API와 DB 접속 없이 로컬 corpus에서 검색한다.

두 검색기 모두 동점은 `doc_id` 오름차순이다. BM25의 일치 토큰이 없어도
풀링 후보 확보를 위해 0점 결과를 포함한다. 이때 후보가 반환됐다고 관련 공고가
존재한다는 뜻은 아니다. 최종 관련도는 별도로 판정해야 한다.

## 저장 구조

```text
RAG_evaluation/artifacts/zighang_v1/
├── runs/
│   ├── dense_fixed1000_qwen1536_v1.jsonl
│   └── bm25_kiwi_v1.jsonl
└── manifests/
    ├── dense_fixed1000_qwen1536_v1.json
    └── bm25_kiwi_v1.json
```

run의 한 줄은 `query_id`, `doc_id`, `rank`(1부터 시작), `score`다.
manifest에는 입력·결과 파일 해시, corpus와 쿼리 수, top-k, 검색 설정,
라이브러리 버전, 소스 파일 해시, 생성 시각, 전체 실행 시간을 저장한다.
manifest의 `run_id`는 검색 결과 이름이고 `embedding_run_id`는 DB 임베딩 실험 UUID다.
`elapsed_seconds`에는 로딩·색인·쿼리 임베딩 등이 포함되므로 순수 검색 지연시간이 아니다.

모든 쿼리를 검증한 뒤 결과와 manifest를 저장한다. 기존 이름은 덮어쓰지 않는다.
완료 manifest가 없거나 결과 파일의 해시가 일치하지 않으면 풀링 입력으로 사용하지 않는다.
검색 도중 실패하면 결과를 저장하지 않으며 Dense 재실행 시 쿼리 임베딩 비용이 다시 든다.
`artifacts/`는 Git에서 제외한다. `pools/`, `labels/`, `qrels/`, `reports/`는
후속 풀링·라벨링 단계에서 생성한다.

## 검증

```bash
python -m pytest test/rag_evaluation/test_retrieval.py -q
supabase db lint --local
```

`test/rag_evaluation/dense_search.sql`은 DB에서 공고별 최고 점수, 서로 다른 차원 run의
격리, 잘못된 쿼리 차원, 미완료 run, 공개 권한 차단을 검사하고 테스트 데이터를 롤백한다.
`psql -v ON_ERROR_STOP=1`로 실행한다.

라이브러리 참고: [rank-bm25](https://github.com/dorianbrown/rank_bm25),
[Kiwi Python API](https://github.com/bab2min/kiwipiepy).
