# 작업 인계 문서

## 완료된 작업

- [x] 기존 AI 배치 서비스 구현·배포
  - Ingestion → Recommendation → Delivery → SES 흐름 구현
  - Supabase pgvector, ECS Fargate, EventBridge Scheduler, Pulumi 구성
  - GitHub Actions와 AWS OIDC 작업 PR #2 병합
- [x] FastAPI 기본 애플리케이션 구성
  - `GET /api/v1/health` 구현
  - `POST /api/v1/sources` 요청·응답 스키마와 `201 Created` 구성
  - 잘못된 URL 요청에 대한 Pydantic 검증과 `422` 테스트 작성
- [x] 외부 서비스 클라이언트 공통화
  - `ai_graphs/shared/clients.py`를 `integrations/clients.py`로 이동
  - 배치와 FastAPI가 같은 Supabase 클라이언트 팩토리를 사용하도록 변경
  - `SUPABASE_URL` 우선, `SUPABASE_PROJECT_ID` 대체 경로 지원
- [x] Source 저장 계층 기반 구성
  - `sources` 테이블 migration 작성
  - UUID PK, URL UNIQUE, 생성 시각, 이름 길이 검사 구성
  - RLS 활성화와 `service_role` 전용 권한 구성
  - 로컬 `supabase db reset`과 Table Editor 검증 완료
  - `SupabaseSourceRepository`와 FastAPI dependency 작성
- [x] Source API와 Repository 연결
  - `SourceRepository` Protocol 추가
  - `POST /api/v1/sources`에서 임시 UUID 생성을 제거
  - FastAPI `Depends`로 Repository를 주입해 `repository.create(source)` 호출
  - 테스트에서 dependency override로 `FakeSourceRepository` 사용
  - UUID와 `created_at`은 FastAPI가 아니라 PostgreSQL이 생성하며, Fake는 DB 응답을 모사함
- [x] Source Repository 단위 테스트
  - 실제 `SupabaseSourceRepository`에 Mock Supabase Client 주입
  - `table → insert → execute` 호출과 정상 응답 파싱 검증
  - 빈 응답, 리스트가 아닌 응답, 복수 행, 잘못된 행 형식 검증
  - 실제 Supabase 네트워크 요청 없이 Repository 로직만 테스트
- [x] Source 중복 URL 처리
  - PostgreSQL unique violation 코드 `23505`를 `SourceAlreadyExistsError`로 변환
  - FastAPI 엔드포인트에서 도메인 오류를 `409 Conflict`로 변환
  - 정상 생성 `201`, 잘못된 URL `422`, 중복 URL `409` API 테스트 완료
- [x] Source 생성 기능 로컬 통합 검증
  - 코드 포맷 정리와 기능 커밋 `8505b89` 완료
  - 로컬 Supabase Secret Key로 FastAPI 연결
  - `POST /api/v1/sources` 실제 요청에서 `201 Created` 확인
  - PostgreSQL이 생성한 UUID와 `created_at` 응답 및 Table Editor 저장 확인
  - `.env.local`을 `.gitignore`에 추가해 로컬 Secret Key 커밋 방지
- [x] 사이트별 크롤링 규칙 테이블 구성
  - `sources 1:N source_crawl_rules` 관계 migration 작성
  - 사이트별 `version`과 JSON 형식의 `rule_schema_version` 분리
  - 규칙 생명주기 `candidate / active / retired / rejected` 구성
  - 최초 검증 상태 `pending / passed / failed` 구성
  - active 규칙만 `unknown / healthy / degraded / broken` 운영 상태를 갖도록 CHECK 구성
  - Source당 active 규칙 하나만 허용하는 partial unique index 구성
  - JSON object 형태의 `rule_definition`, 생성 주체, 검증 시각 저장
  - RLS 활성화와 `service_role` 전용 권한 구성
  - 로컬 migration 적용과 DB lint, 제약조건 검증 완료
- [x] Crawl4AI CSS 규칙 모델 기반 구성
  - MVP에서는 XPath와 URL 패턴 전략을 별도로 지원하지 않고 CSS 스키마만 사용하기로 결정
  - `CrawlRuleDefinition`으로 공지 행의 `baseSelector`와 추출 필드를 표현
  - `CrawlRuleField`로 `text`와 `attribute` 추출 규칙 표현
  - 규칙마다 하나 이상의 추출 필드를 요구
  - `attribute` 타입에 속성명이 없으면 Pydantic 검증 실패
  - Crawl4AI 전달 시 `model_dump(mode="json", by_alias=True, exclude_none=True)` 사용
  - CSS 규칙 정상 직렬화와 잘못된 attribute 규칙 단위 테스트 작성
- [x] `source_crawl_rules` DB 행 Pydantic 모델 작성
  - `SourceCrawlRuleCreate`는 candidate 생성 입력만 받는다
  - `SourceCrawlRuleResponse`는 테이블 전체 행을 표현한다
  - active 규칙만 `health_status`를 갖고, inactive는 `None`이어야 한다
- [x] `SourceCrawlRuleRepository` 구현
  - `create_candidate`는 Source별 최대 `version + 1`을 넣어 저장한다
  - `get_active`는 Source의 active 규칙 한 행을 조회하고 없으면 `None`을 반환한다
  - `update_validation_status`는 passed/failed일 때 `validated_at`을 기록하고 pending이면 비운다
  - `update_health_status`는 active 규칙만 변경한다
  - `activate`는 기존 active를 먼저 retired로 바꾼 뒤 대상 규칙을 active + `unknown`으로 전환한다
  - Mock Client 단위 테스트 18개 작성
  - 스키마 테스트와 모듈명이 겹치지 않도록 Repository 테스트 파일명은 `test_source_crawl_rule.py`를 사용한다
- [x] 건국대 공지 CSS 스키마 생성 로컬 검증
  - `JsonCssExtractionStrategy.generate_schema`로 title/url 규칙을 만들었다
  - `schema_type`은 `"CSS"`여야 한다. 문서 예시의 `"css"`는 XPath 프롬프트가 나간다
  - 생성 스키마는 `table.board-table tbody tr`과 `td.td-subject` 링크를 사용한다
  - 같은 HTML에서 공지 29개를 추출했고, 제목 칸 링크는 모두 `artclView.do`였다
  - 실험 스크립트는 `test/mvp2/test_generate_schema.py`이며 기본 pytest에서는 skip한다
- [x] 건국대 규칙을 로컬 DB에 저장
  - `sources`에 건국대 공지 URL이 있다
  - `seed_konkuk_rule.py`로 candidate 생성 후 activate 했다
  - `load_dotenv(".env.local", override=True)`가 원격 `.env` 키를 덮어쓴다
- [x] Ingestion DB Source 조회
  - `SourceRepository.list_all` 추가
  - `load_sources()`가 `sources` + active 규칙을 합쳐 배치 `Source`를 만든다
  - active 규칙 없는 사이트는 건너뛴다
- [x] 목록 추출을 CSS 규칙으로 변경
  - `crawl_source_page()`는 `artclView.do` 필터 대신 `JsonCssExtractionStrategy.extract`를 사용한다
  - 상대경로 url은 `urljoin`으로 절대경로가 된다
  - `NoticeTarget.source_id`는 Source UUID이다
  - CSS 추출 예외는 해당 Source만 `errors`에 기록하고 다른 Source는 계속 처리한다
- [x] 배치 source_id를 UUID로 통일
  - `NoticeTarget`과 `Notice`의 `source_id`는 UUID다
  - `notice_chunks.source_id`에는 문자열로 저장한다. 컬럼 타입은 아직 text다
- [x] `activate()`는 `validation_status=passed`인 규칙만 활성화한다
  - 이미 active인 규칙은 검증 상태와 관계없이 그대로 반환한다
  - pending/failed 활성화는 `RuntimeError`다
- [x] `load_sources()` 단위 테스트
  - Source + active 규칙 결합, active 없는 Source 제외, 빈 목록 처리
- [x] 로컬 Supabase `load_sources` → CSS 목록 추출 통합 검증
  - 건국대 Source 1건과 active 규칙을 읽었다
  - 공지 상세 URL 30개를 추출했고 오류는 없었다
- [x] 크롤링 규칙 생성 FastAPI 구현
  - `POST /api/v1/sources/{source_id}/crawl_rules` 엔드포인트와 라우터를 추가했다
  - `SourceRepository.get_by_id`로 등록된 Source를 조회한다
  - Source HTML을 가져와 Crawl4AI와 OpenRouter LLM으로 CSS 스키마를 생성한다
  - `target_json_example`은 단일 객체의 `title`, `url` 필드를 사용한다
  - Crawl4AI `validate=True`, `max_refinements=3`으로 스키마 보정을 시도한다
  - 생성된 스키마를 같은 HTML에 적용해 `title`, `url`이 채워진 공지가 있는지 다시 검증한다
  - candidate 저장 후 검증 성공 시 `passed → active`, 실패 시 `failed`로 전환한다
  - Source 없음은 `404`, 규칙 검증 실패는 `422`, 외부 크롤링·LLM 실패는 `502`로 응답한다
- [x] SSRF 1차 URL 검증 구현
  - `validate_public_url()`로 HTTP(S), 80·443 포트, 인증정보 미포함 URL만 허용한다
  - IP literal과 DNS의 모든 IPv4·IPv6 결과가 공개 주소인지 확인한다
  - loopback, private, link-local, metadata, multicast, reserved 주소를 차단한다
  - Source 등록 시 DB 저장 전에 검사하고 실패하면 `422`를 반환한다
  - 크롤링 직전 다시 검사하며, 비동기 이벤트 루프를 막지 않도록 `asyncio.to_thread()`를 사용한다
  - 안전하지 않은 Source는 Repository 저장이나 브라우저 실행까지 도달하지 않는다
- [x] 포트폴리오 관점의 프로젝트 진행 방향 재정립
  - 기능 나열보다 문제 정의 → Baseline → 평가 → 실패 분석 → 개선 결과를 남기는 방향으로 전환한다
  - 현재 구현은 다중 사이트를 지원할 수 있는 구조지만 실제 통합 검증은 건국대 한 곳뿐임을 확인했다
  - 핵심 딥다이브는 다중 사이트 수집 품질 검증 후 RAG 추천 품질 고도화로 정했다
  - LangGraph 제거는 목표로 삼지 않고 Plain Python과 복잡도·테스트·디버깅·오버헤드를 비교한 뒤 결정한다
  - 사용자 DB, Chat, 웹 UI는 폐기하지 않고 RAG 개선 가설을 검증하는 순서에 맞춰 이후 구현한다
- [x] 상세 공지 제목·본문 CSS Rule 구현
  - `source_crawl_rules.detail_rule_definition` nullable JSONB migration을 추가하고 로컬 DB에 적용했다.
  - 상세 Rule이 있는 candidate는 `rule_schema_version=2`로 저장하며, 기존 목록 Rule만 있는 v1·v2 행은 legacy fallback을 유지한다.
  - 규칙 생성 API는 목록 Rule로 고유한 상세 공지 최대 3개를 고르고, 첫 상세 페이지로 title/content Rule을 생성한다.
  - 이미지·첨부 중심 공지가 있어 3개 모두 본문을 요구하지 않고, 1~2개 샘플은 전부·3개 샘플은 최소 2개 통과 시 활성화하도록 구현했다.
  - Ingestion은 상세 Rule이 있으면 실제 title/content만 저장하고, 상세 추출 실패 공지의 기존 chunk를 삭제해 오염된 과거 데이터가 RAG에 남지 않게 했다.
  - 목록에서 추출한 title은 상세 title이 비었을 때 fallback으로 사용한다.
  - 당시 Crawl4AI 0.9.2 호환을 위해 `gemini/gemini-2.5-flash`를 썼고, 이후 OpenRouter `google/gemini-3.6-flash`로 바꿨다.
- [x] 상세 Rule 로컬 E2E 검증
  - migration 적용과 `supabase db lint --local`이 통과했다.
  - 건국대 Source `f25944ce-c864-497b-9c74-df5bdaff229d`에 v4 규칙이 `active/passed`로 전환됐다.
  - v3은 상세 샘플 한 건의 빈 텍스트 본문 때문에 `failed` candidate로 보존됐다.
  - v4 배치에서 16개 chunk를 실제 상세 title/content로 저장하고, 본문을 추출하지 못한 8개 공지는 오류 격리·기존 chunk 삭제를 확인했다.
  - 기존 raw Markdown으로 저장된 `title = 건국대학교 -` chunk 9개는 로컬 DB에서 삭제했다. 원본 공지에서 재수집 가능하다.
- [x] 상세 공지 URL-본문 정합성 검증
  - Crawl4AI `arun_many()`의 반환 순서가 요청 순서와 다를 수 있어, 결과의 `url`로 원래 요청 순서에 다시 정렬하도록 수정했다.
  - 결과를 역순으로 반환하는 단위 테스트와 실제 건국대 E2E로 제목·본문·URL이 같은 공지를 가리키는지 검증했다.
  - Energy Summer Academy 공지는 올바른 URL `1200589`로 저장·SES 발송됐고, 잘못 연결됐던 `1202619` chunk는 삭제됐다.
- [x] Gemini 일일 한도 대응으로 OpenRouter 전환
  - generation/embedding 모두 `OPENROUTER_API_KEY`를 사용한다.
  - 현재 generation은 `google/gemini-3.6-flash`, embedding은 `qwen/qwen3-embedding-8b`다.
  - Crawl4AI provider는 `openrouter/{GENERATION_MODEL}`이다. 상수는 `integrations/clients.py`에 있다.
  - 기존 `notice_chunks` 차원과 맞추려고 embedding `dimensions=1536`을 유지한다.
  - GraphContext는 `gemini_client` 대신 `embedding_client`(OpenAI SDK)다.
- [x] 목록 CSS 생성 프롬프트를 공고/공지 목적 지향으로 변경
  - `LIST_SCHEMA_QUERY`는 테이블 행이 아니라 반복 항목의 title/url을 뽑도록 바꿨다.
  - 루트가 이미 `a`면 url은 자식 `a`가 아니라 `baseFields` href를 쓰라고 명시했다.
- [x] 루트 링크 url 보정
  - `_normalize_root_link_url()`이 `baseSelector`가 `a`인데 `fields.url.selector`가 자식 `a`인 스키마를 `baseFields.href`로 옮긴다.
  - 직행 카드가 `<a class="relative" href="/recruitment/...">`인 경우를 위한 안전망이다.

## 진행 중인 작업

- [ ] 직행(`https://zighang.com/it`) 크롤링 규칙 생성 E2E
  - Source id: `36701990-2c33-4979-801d-cbaf59c04154`
  - curl: `list_crawl_mode=infinite_scroll`, `detail_crawl_mode=dynamic`
  - `google/gemini-3.6-flash`로 목록 스키마는 통과했다. `baseSelector: main div.grid > a`, title 40건 + url 40건.
  - 같은 날 반복 크롤 후 헤드리스가 anti-bot에 막혔다. 페이지는 131바이트/가시 문자 20자라 502가 났다.
  - 일반 브라우저에서는 열린다. 내일 재시도가 우선이다.
  - 상세 Rule 생성·3샘플 검증까지는 아직 못 갔다.
- [ ] RAG 평가 데이터셋 (`feat/rag-eval-dataset`)
  - 목표 순서: 데이터셋(qrels, TREC pooling) → 벤치마크 시스템 → 기존 RAG 평가 → query prefix → 청킹 → Retrieval → Reranker → dimension
  - 평가 corpus는 건국대 공지 대신 직행 채용공고를 쓰려 했다.
  - 평가 임베딩은 운영 `notice_chunks`와 분리된 테이블이 필요하다. 아직 안 만들었다.
- [ ] 수집 데이터 품질 후속 정리
  - 이미지·첨부 중심 공지는 `div.view-con`에 텍스트가 없어 상세 Rule에서 제외된다.
  - 상세 Rule 적용 후 SES를 포함한 전체 재발송 E2E는 추천 후보가 0개여서 다시 검증하지 않았다. 이전 목록 Rule 기준 SES 발송과 중복 발송 이력은 확인했다.
- [ ] SSRF 브라우저 요청 가드
  - 등록 시점과 배치 목록·상세 URL의 브라우저 실행 직전 URL 검증까지 완료했다
  - Crawl4AI `on_page_context_created`와 Playwright `page.route()`를 이용한 redirect·추가 요청 차단은 다음 세션으로 보류했다
- [ ] 사용자·구독 관리
  - 당장 구현하지 않고 수집·RAG 딥다이브 이후 진행한다
  - `users`, `subscriptions`, `user_preferences`, `recommendation_feedback`를 최소 범위로 구성할 예정이다
- [ ] RAG 딥다이브 준비
  - 현재 1,000자 고정 청킹, Dense Search, 유사도 0.65, 자체 점수 공식을 Baseline으로 고정한다
  - 실제 공지와 사용자 프로필에 relevance 정답을 붙인 평가 데이터셋은 아직 없다
  - Precision@K, Recall@K, nDCG@K, 추천 없음 정확도, 지연시간을 기준으로 개선안을 비교할 예정이다

## 다음에 해야 할 작업

1. 내일 직행 크롤 규칙 생성을 다시 친다. 브라우저에서 `https://zighang.com/it`가 열리는지 확인한 뒤 같은 curl을 보낸다. 목록은 Gemini 3.6 Flash로 이미 한 번 통과했다.
2. 여전히 anti-bot이면 Crawl4AI stealth/User-Agent를 검토한다. 지금은 `BrowserConfig(headless=True)`만 쓴다.
3. 목록 통과 후 상세 Rule 생성과 3샘플 검증까지 E2E를 끝낸다.
4. Qwen embedding으로 바꾼 뒤 기존 Gemini 벡터와 섞이면 검색이 깨진다. 평가용은 별도 테이블, 운영 재임베딩은 따로 결정한다.
5. ECS/SSM은 아직 `GOOGLE_API_KEY`다. 배포 전에 `OPENROUTER_API_KEY`로 바꿔야 한다.
6. 이미지·첨부 중심 공지는 텍스트 RAG 대상에서 제외할지, OCR·첨부 텍스트 추출을 별도 기능으로 둘지 결정한다. 현재는 제외가 구현된 동작이다.
7. 실제 상세 title/content만 남은 현재 corpus에서 RAG Baseline을 다시 측정한다. 추천 후보가 0개인 원인을 먼저 기록한다.
8. 이후 청킹, 제목+본문 임베딩, Hybrid Search, metadata filter, reranker를 한 번에 하나씩 비교한다.
9. Crawl4AI `on_page_context_created`와 Playwright `page.route()`로 redirect·JavaScript 이동·서브리소스 SSRF 요청 가드를 완성한다.

## 중기 로드맵

```text
현재 E2E 완성
→ 다중 사이트 수집 품질 검증·개선
→ RAG 평가 데이터셋·Baseline
→ RAG 저장·검색 고도화
→ 백엔드·DB 안정성 검증
→ LangGraph와 Plain Python 비교
→ 사용자 DB·추천 피드백
→ Chat 프로필 효과 검증
→ 최소 웹 UI 배포
→ 포트폴리오·블로그 정리
```

관계 모델은 다음을 기준으로 한다.

```text
users 1 ── N subscriptions N ── 1 sources
```

- 한 사용자는 여러 Source를 구독할 수 있다.
- 하나의 Source도 여러 사용자가 구독할 수 있다.
- 추천 검색어는 이후 `user_queries` 테이블 또는 MVP용 JSONB 중 하나를 결정한다.

## 주의사항

- `POST /api/v1/sources`는 이제 Repository를 호출한다. 테스트 override가 없으면 실제 Supabase Client가 사용된다.
- UUID와 `created_at`은 `sources` 테이블의 기본값으로 PostgreSQL이 생성한다.
- `FakeSourceRepository`는 API 테스트용이며 `test/api/test_sources.py`에만 둔다.
- Repository 테스트는 실제 Repository와 Mock Client를 조합한다. Mock Repository 테스트가 아니다.
- `sources` migration은 로컬에서만 검증했으며 원격 Supabase에는 적용하지 않았다.
- `source_crawl_rules` migration도 로컬에만 적용했으며 원격 Supabase에는 적용하지 않았다.
- inactive 규칙의 `health_status`는 `NULL`이고 active 규칙만 운영 상태값을 갖는다.
- 규칙은 실행 코드나 URL 패턴이 아니라 Crawl4AI CSS 스키마를 `rule_definition` JSONB에 저장한다.
- CSS 규칙은 수동 작성하지 않는다. Crawl4AI가 LLM으로 스키마를 만들고, 이후 크롤링은 그 스키마만 반복 실행한다.
- 생성 API는 `JsonCssExtractionStrategy.generate_schema(html=..., query=..., llm_config=LLMConfig(...), validate=True)`이다. `html` 대신 `url`을 넘길 수도 있다.
- `schema_type`은 `"CSS"`처럼 대문자여야 한다. `"css"`를 넣으면 XPath 프롬프트가 나간다.
- Playwright 브라우저가 없으면 `playwright install chromium`이 필요하다.
- 생성 스키마의 url은 상대경로일 수 있다. 이후 절대 URL로 바꿔야 한다.
- 이 기능은 매 크롤마다 LLM을 쓰는 `LLMExtractionStrategy`와 다르다. 스키마 생성은 한 번, 추출은 LLM 없이 한다.
- `generated_by`의 `llm` 값이 이 생성 경로를 표시한다. 건국대 셀렉터 초안은 예시일 뿐 시드로 쓰지 않는다.
- `CrawlRuleDefinition.fields`는 tuple이므로 Crawl4AI 전달 시 `model_dump(mode="json", by_alias=True, exclude_none=True)`로 직렬화한다.
- Supabase CLI는 프로젝트 루트에서 실행하고 Docker Desktop이 필요하다.
- `supabase db reset`은 로컬 DB를 초기화한다. 원격 DB를 지우는 `--linked`를 붙이지 않는다.
- `.env`, `.env.local`, Supabase Secret Key, API key, AWS 인증정보를 커밋하지 않는다.
- 루트 `main.py`는 실제 크롤링·OpenRouter embedding·Supabase·SES 요청을 실행한다.
- 생성 LLM과 임베딩은 OpenRouter다. 키는 `OPENROUTER_API_KEY`. 모델 상수는 `integrations/clients.py`의 `GENERATION_MODEL`, `EMBEDDING_MODEL`.
- 시도했던 generation 모델: `google/gemma-3-27b-it`(CSS 선택자 불안정), `qwen/qwen3-32b`(너무 느림), 현재 `google/gemini-3.6-flash`.
- Gemma는 루트 `a`의 href를 자식 `a`로 찾거나, 안쪽 div class를 바깥 `a`에 붙이는 실수를 자주 했다. 프롬프트+`_normalize_root_link_url`은 전자만 보정한다.
- 직행 카드 마크업은 `<a class="relative" href="/recruitment/{uuid}"><div class="fade-in bg-primary-light group ...">`다.
- 오늘 후반 직행 크롤은 Crawl4AI anti-bot detector가 `minimal_text`로 실패했다. 실제 브라우저에서는 열린다. 같은 IP 반복 크롤이 원인일 가능성이 크다.
- Qwen embedding과 기존 Gemini embedding을 같은 `notice_chunks`에 섞지 않는다. 차원은 둘 다 1536이어도 공간은 다르다.
- `ai_graphs/ingestion_graph/tools.py`의 `setup_gemini_model`은 아직 Gemini leftover다. 사용 경로가 아니면 나중에 정리한다.
- 인프라 `infra/ecs.py` secrets는 아직 `GOOGLE_API_KEY`다.
- `test/mvp1/requests_test.py`는 import 시 네트워크 요청을 실행하므로 전체 `pytest`는 피한다.
- `SourceCrawlRuleRepository`는 Ingestion `load_sources`와 `POST /api/v1/sources/{source_id}/crawl_rules`에서 쓰인다.
- uvicorn `--reload --env-file .env.local`만으로는 자식 프로세스에 `SUPABASE_URL`이 없을 수 있다. 로컬 API는 `.env.local`을 셸에 source한 뒤 실행한다.
- `seed_konkuk_rule.py`는 이 브랜치에서 삭제됐다. 건국대 규칙은 DB의 active 행을 사용한다.
- `activate`는 이미 active가 아니면 `validation_status=passed`만 허용한다. 시드 스크립트는 활성화 전에 passed로 바꾼다.
- `version` 번호는 max+1이라 동시 생성 시 unique violation이 날 수 있다. MVP에서는 나중에 처리한다.
- `update()` payload는 `dict[str, str | None]`이며 Supabase JSON 타입으로 `cast`한다.
- 현재 Ingestion은 `sources`와 active 규칙을 읽고 CSS로 목록 URL을 추출한다. `data/userURL.json`은 더 이상 읽지 않는다.
- 기존 `notice_chunks.source_id`는 문자열이고 신규 `sources.id`는 UUID이므로 연결 전 migration 전략이 필요하다.
- `validate_public_url()`은 DNS 조회 결과를 검사하지만 DNS 검사와 Chromium 연결 사이의 DNS rebinding 가능성은 남는다. 공개 배포 전 outbound proxy 또는 네트워크 계층 차단도 필요하다.
- 현재 SSRF 방어는 Source 등록과 크롤링 직전 검사까지만 적용됐다. redirect와 브라우저 서브리소스는 아직 요청 전에 차단하지 않는다.
- `detail_rule_definition`이 없는 legacy active 규칙은 metadata 제목과 전체 Markdown을 계속 사용한다. 새 규칙을 생성하면 schema version 2와 상세 Rule을 갖는다.
- 현재 건국대 v4 상세 Rule은 `div.board-view-info h2.view-title`과 `div.view-con`을 사용한다. 본문이 이미지·첨부만인 공지는 텍스트가 비어 제외된다.
- 상세 추출 실패는 네트워크 실패와 다르게 `invalid_notice_ids`에 기록되며, 이후 `upsert_to_vectorDB()`가 해당 notice_id의 기존 chunk를 삭제한다.
- 목록 HTML에 pinned row와 일반 row가 함께 있어도, 같은 절대 상세 URL은 첫 `NoticeTarget` 하나만 유지한다.
- `arun_many()` 결과는 요청 배열 순서를 보장한다고 가정하지 않는다. 결과 `url`이 요청 URL과 일치할 때만 연결하고, 일치하지 않으면 해당 URL을 실패로 기록한다.
- `main.py` E2E는 최신 상세 Rule 기준 15개 저장·7개 추출 실패를 확인했다. 실제 저장 공지를 대상으로 추천 1건과 SES 발송 1건, 같은 공지의 중복 발송 차단을 검증했다.
- 다중 사이트를 지원하는 코드 구조는 있으나 실제 규칙 생성·추출 통합 검증은 건국대 한 곳뿐이다. 평가 전에는 다중 사이트 성능을 완성된 사실처럼 표현하지 않는다.
- RAG의 1,000자 청킹, 유사도 0.65와 0.8/0.2 점수 가중치는 아직 평가 데이터로 검증되지 않은 Baseline이다.
- Chat은 Agent의 증거가 아니라 사용자 프로필 수집 인터페이스다. 정적 프로필 대비 추천 품질 개선을 측정할 수 있을 때 도입한다.
- 기능 확장을 영구 중단한 것이 아니다. 수집·RAG 실험에서 확인한 문제를 해결하는 순서로 사용자 DB, Chat, 웹 UI를 구현한다.
- Source 등록 API는 실제 DNS 조회를 수행한다. 테스트에서는 `validate_public_url`을 Mock해 외부 네트워크 요청을 막는다.
- `fetch_html()`의 URL 검증은 `asyncio.to_thread()`에서 실행한다.
- 크롤링 규칙 생성 엔드포인트 안의 동기 Supabase Repository 호출은 현재 이벤트 루프에서 실행된다. 트래픽 증가 시 비동기 Client 또는 thread offload를 검토한다.
- `activate()`는 기존 active를 retire한 뒤 새 규칙을 active로 만드는 두 번의 DB 요청이므로 완전한 트랜잭션은 아니다.
- 테스트 시 Requests 의존성 불일치 경고와 Starlette `TestClient`의 httpx 사용 중단 예정 경고가 남아 있다.
- 프로젝트 규칙상 `main`/`master` 브랜치에 직접 Push하지 않는다.

## 관련 파일

- `app/main.py` - FastAPI 애플리케이션 진입점
- `app/api/router.py` - API v1 라우터 조립
- `app/api/endpoints/sources.py` - Source 등록 엔드포인트와 Repository 주입
- `app/api/endpoints/crawl_rules.py` - CSS 크롤링 규칙 생성 엔드포인트
- `app/services/crawl_rule.py` - HTML 수집, 스키마 생성·검증, 루트 `a` url 보정, candidate 상태 전환과 활성화
- `app/api/dependencies.py` - Supabase, Source와 Crawl Rule Repository dependency
- `app/schemas/source.py` - Source 요청·응답 스키마
- `app/repositories/source.py` - SourceRepository Protocol과 Supabase 구현. `list_all`, `get_by_id` 포함
- `app/exceptions.py` - Source와 크롤링 규칙 도메인 오류
- `integrations/clients.py` - OpenRouter·Supabase 공통 클라이언트와 generation/embedding 모델 상수
- `integrations/crawl_config.py` - default/dynamic/infinite_scroll Crawl4AI 실행 설정
- `test/integrations/test_clients.py` - OpenRouter 키 검사와 embedding 파싱 테스트
- `docs/rag-eval-dataset.md` - RAG 고도화 브랜치 목표 목록
- `integrations/url_safety.py` - URL 형태·DNS·공개 IP 기반 SSRF 1차 검증
- `supabase/migrations/20260814051424_create_sources.sql` - sources 테이블 migration
- `supabase/migrations/20260819000000_create_source_crawl_rules.sql` - 사이트별 버전형 크롤링 규칙 migration
- `app/schemas/crawl_rule.py` - 크롤링 규칙 상태, CSS 스키마, DB 행 모델
- `app/repositories/crawl_rule.py` - SourceCrawlRuleRepository Protocol과 Supabase 구현
- `supabase/migrations/20260901000000_add_detail_rule_definition.sql` - 상세 Rule JSONB 컬럼과 객체 제약
- `test/schemas/test_crawl_rule.py` - CSS 규칙 직렬화와 필드 검증 테스트
- `test/repositories/test_source_crawl_rule.py` - Mock Client를 사용하는 크롤링 규칙 Repository 단위 테스트
- `test/mvp2/test_generate_schema.py` - 건국대 공지 generate_schema 로컬 실험. `RUN_GENERATE_SCHEMA_TEST=1`일 때만 pytest가 실행한다
- `test/api/test_sources.py` - Fake Repository를 사용하는 Source API 테스트
- `test/api/test_crawl_rules.py` - 크롤링 규칙 생성 API 오류 응답 테스트
- `test/repositories/test_source.py` - Mock Client를 사용하는 실제 Repository 단위 테스트
- `test/services/test_crawl_rule_service.py` - 스키마 검증·상태 전환·URL 재검증 테스트
- `test/integrations/test_url_safety.py` - 공개·사설 IP와 DNS URL 정책 테스트
- `ai_graphs/ingestion_graph/models.py` - 배치용 Source, 목록 제목과 상세 Rule을 갖는 NoticeTarget
- `ai_graphs/ingestion_graph/nodes.py` - 목록·상세 CSS 추출, legacy fallback, 무효 공지 chunk 정리
- `data/userURL.json` - DB 전환 전 임시 Source 입력. Ingestion은 더 이상 사용하지 않음
- `data/userInfo.md` - DB 전환 전 임시 사용자·추천 Query 입력

## 마지막 상태

- 브랜치: `feat/rag-eval-dataset`
- 마지막 커밋: `4005be0` Merge pull request #6 from otteru/ci/supabase-migrations
- 오늘 작업은 커밋하지 않았다. OpenRouter 전환, 프롬프트, url 보정, crawl_mode migration 등이 working tree에 남아 있다.
- 테스트: 관련 단위 테스트는 통과했다. 직행 규칙 생성 E2E는 anti-bot로 중단됐다.
- 로컬 API: `uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`
- 재개 curl:

```bash
curl --max-time 300 \
  -X POST "http://127.0.0.1:8000/api/v1/sources/36701990-2c33-4979-801d-cbaf59c04154/crawl_rules" \
  -H "Content-Type: application/json" \
  -d '{
    "list_crawl_mode": "infinite_scroll",
    "detail_crawl_mode": "dynamic"
  }'
```

- 다음 세션 시작: `docs/HANDOFF.md 읽고 직행 크롤 규칙 생성부터 이어서 진행해줘`
