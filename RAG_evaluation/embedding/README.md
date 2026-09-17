# 평가 corpus 임베딩

`1000-character-embedding.py`는 기존 ingestion과 동일하게 본문을 Python 문자열
1,000자씩 겹침 없이 분할한다. 공백만 있는 청크는 제외하며 실제 입력은
`title: {title} | text: {chunk}`이다. 기본 모델은 Qwen3 Embedding 8B, 차원은 1536이다.
검색 쿼리는 이 기준 실험에서 `text: {query}`로 임베딩해야 한다.

## 실행

프로젝트 루트에서 `conda activate infohelper` 후 실행한다.

```bash
# 네트워크·환경 파일 접근 없이 전체 문서/청크 수와 입력 예시 확인
python RAG_evaluation/embedding/1000-character-embedding.py --dry-run

# 로컬 Docker/Supabase 시작 후 평가 테이블 적용
supabase start
supabase migration up --local

# corpus 전체 등록 후 앞 5개 공고의 모든 청크만 임베딩
python RAG_evaluation/embedding/1000-character-embedding.py --limit-documents 5

# 같은 run에서 저장된 청크를 건너뛰고 전체 실행
python RAG_evaluation/embedding/1000-character-embedding.py --batch-size 128
```

`.env`를 먼저 읽고 `.env.local`이 덮어쓴다. 다른 대상은 `--env-file`로 명시한다.
파일이 없으면 실행을 중단한다. DB 대상은 선택한 환경 파일의 `SUPABASE_URL`이다.
API 키나 벡터는 진행 로그에 출력하지 않는다.

`--batch-size` 기본값은 기존과 같은 1이다. 여러 입력을 한 요청으로 보내더라도
각 입력 문자열·모델·차원은 유지하며, 응답 index로 청크와 벡터를 연결한다.
provider의 배치 입력 지원 여부는 소량 실행으로 먼저 확인한다.

## 실험과 재개

- 원본: `eval_documents`의 `(corpus_version, doc_id)`로 식별한다.
- 설정: `eval_embedding_runs`에 파일 SHA-256, 모델, 차원, 입력 템플릿, 예상 수를 보존한다.
- 결과: `eval_chunks`의 `(run_id, doc_id, chunk_index)`로 식별한다.
- 원본·청크는 insert만 허용하고, run은 상태만 변경할 수 있다.
- 같은 corpus 버전으로 다른 파일 해시를 등록하면 DB에서 차단한다.
- 같은 run 이름으로 다른 설정을 사용하면 중단한다. 새 설정은 새 이름을 사용한다.
- 소량 실행 후 전체 수가 부족하면 `pending`, 오류가 발생하면 `failed`로 남는다.
- 실행 중단 후 같은 명령으로 재개하면 DB에 저장된 청크를 다시 호출하지 않는다.
- 강제 종료로 `running`이 남았다면 기존 프로세스 종료를 확인한 뒤 `--resume-running`을 사용한다.
- 같은 run을 여러 프로세스에서 동시에 실행하지 않는다.
- API 응답 후 DB 저장 전에 실패한 배치는 재개 시 API를 다시 호출할 수 있다.
- 모든 예상 청크의 식별자·입력이 확인되고 문서/청크 수가 일치할 때만 `completed`가 된다.

다른 차원은 예를 들어 `--dimensions 1024 --run-name fixed1000_qwen1024_v1`처럼 실행한다.
차원을 지정하지 않은 `vector` 컬럼을 사용하지만, 청크 차원은 run 차원과 외래키로
연결되고 실제 벡터 길이도 검사한다. 검색은 항상 하나의 완료된 run으로 제한한다.
모델의 해당 차원 지원 여부는 별도로 확인해야 한다.

## 검증

```bash
python -m pytest test/rag_evaluation/test_fixed_character.py test/integrations/test_clients.py -q
supabase db lint --local
```

`test/rag_evaluation/eval_schema.sql`은 실제 PostgreSQL에서 해시·복합 외래키·차원·권한·
완료 조건을 검사하고 테스트 데이터는 전부 롤백한다. `psql -v ON_ERROR_STOP=1`로 실행한다.

2026-09-09 로컬 검증: `zighang_v1` 공고 4,681건, 청크 5,603개를 저장했다.
`fixed1000_qwen1536_v1`의 모든 벡터는 1,536차원이며 상태는 `completed`다.
기존 `_split_text()`와 전체 공고의 청킹 결과가 일치하고, DB의 임베딩 입력과
원본 제목·청크 연결 불일치는 0건이다. 128개 단위 배치 요청도 실제 API로 검증했다.
