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
  - Source HTML을 가져와 Crawl4AI와 Gemini로 CSS 스키마를 생성한다
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

## 진행 중인 작업

- [ ] 사이트별 크롤링 규칙 생성 API 마무리
  - DB, Repository, 생성 API, 스키마 검증, candidate 상태 전환과 활성화까지 구현했다
  - 단위·API 테스트는 통과했지만 실제 Supabase·Gemini·Crawl4AI를 연결한 로컬 E2E는 아직 실행하지 않았다
- [ ] SSRF 브라우저 요청 가드
  - 등록 시점과 최초 크롤링 직전 URL 검증까지 완료했다
  - Crawl4AI `on_page_context_created`와 Playwright `page.route()`를 이용한 redirect·추가 요청 차단은 다음 세션으로 보류했다
  - 배치 Ingestion과 추출된 상세 공지 URL에도 같은 검증을 연결해야 한다
- [ ] 사용자·구독 관리
  - `users`와 `sources`의 다대다 관계를 `subscriptions`로 구성할 예정
  - 크롤링 규칙 생성 API와 SSRF 방어를 마무리한 뒤 진행

## 다음에 해야 할 작업

1. Crawl4AI `on_page_context_created` hook에서 Playwright `page.route()`를 등록해 모든 HTTP(S) 요청을 `validate_public_url()`로 검사한다.
2. 안전하지 않은 최초 요청·redirect·JavaScript 이동·서브리소스 요청은 `route.abort()`하고 차단 기록을 바탕으로 크롤링을 실패 처리한다.
3. 배치 Ingestion의 Source URL과 추출된 상세 공지 URL에도 같은 요청 가드를 적용한다.
4. 로컬 Supabase·Gemini·Crawl4AI로 Source 등록 → 규칙 생성 → active 전환 E2E를 검증한다.
5. 이후 사용자·구독 관리와 사용자별 추천·발송으로 진행한다.

## 중기 로드맵

```text
Source 생성 완성
→ 사이트별 크롤링 규칙
→ Ingestion의 DB 기반 Source 조회
→ 사용자 관리
→ 사용자-Source 구독 관계
→ 사용자별 추천·이메일 발송
→ 로컬 E2E와 운영 배포
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
- 루트 `main.py`는 실제 크롤링·Gemini·Supabase·SES 요청을 실행한다.
- `test/mvp1/requests_test.py`는 import 시 네트워크 요청을 실행하므로 전체 `pytest`는 피한다.
- `SourceCrawlRuleRepository`는 Ingestion `load_sources`에서 쓰인다. 규칙 전용 FastAPI 엔드포인트는 아직 없다.
- uvicorn `--reload --env-file .env.local`만으로는 자식 프로세스에 `SUPABASE_URL`이 없을 수 있다. 로컬 API는 `.env.local`을 셸에 source한 뒤 실행한다.
- `seed_konkuk_rule.py`는 로컬 Source UUID가 박혀 있다. 원격 DB에 돌리지 않는다.
- `activate`는 이미 active가 아니면 `validation_status=passed`만 허용한다. 시드 스크립트는 활성화 전에 passed로 바꾼다.
- `version` 번호는 max+1이라 동시 생성 시 unique violation이 날 수 있다. MVP에서는 나중에 처리한다.
- `update()` payload는 `dict[str, str | None]`이며 Supabase JSON 타입으로 `cast`한다.
- 현재 Ingestion은 `sources`와 active 규칙을 읽고 CSS로 목록 URL을 추출한다. `data/userURL.json`은 더 이상 읽지 않는다.
- 기존 `notice_chunks.source_id`는 문자열이고 신규 `sources.id`는 UUID이므로 연결 전 migration 전략이 필요하다.
- `validate_public_url()`은 DNS 조회 결과를 검사하지만 DNS 검사와 Chromium 연결 사이의 DNS rebinding 가능성은 남는다. 공개 배포 전 outbound proxy 또는 네트워크 계층 차단도 필요하다.
- 현재 SSRF 방어는 Source 등록과 크롤링 직전 검사까지만 적용됐다. redirect와 브라우저 서브리소스는 아직 요청 전에 차단하지 않는다.
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
- `app/services/crawl_rule.py` - HTML 수집, 스키마 생성·검증, candidate 상태 전환과 활성화
- `app/api/dependencies.py` - Supabase, Source와 Crawl Rule Repository dependency
- `app/schemas/source.py` - Source 요청·응답 스키마
- `app/repositories/source.py` - SourceRepository Protocol과 Supabase 구현. `list_all`, `get_by_id` 포함
- `app/exceptions.py` - Source와 크롤링 규칙 도메인 오류
- `integrations/clients.py` - Gemini·Supabase 공통 클라이언트 생성
- `integrations/url_safety.py` - URL 형태·DNS·공개 IP 기반 SSRF 1차 검증
- `supabase/migrations/20260814051424_create_sources.sql` - sources 테이블 migration
- `supabase/migrations/20260819000000_create_source_crawl_rules.sql` - 사이트별 버전형 크롤링 규칙 migration
- `app/schemas/crawl_rule.py` - 크롤링 규칙 상태, CSS 스키마, DB 행 모델
- `app/repositories/crawl_rule.py` - SourceCrawlRuleRepository Protocol과 Supabase 구현
- `test/schemas/test_crawl_rule.py` - CSS 규칙 직렬화와 필드 검증 테스트
- `test/repositories/test_source_crawl_rule.py` - Mock Client를 사용하는 크롤링 규칙 Repository 단위 테스트
- `test/mvp2/test_generate_schema.py` - 건국대 공지 generate_schema 로컬 실험. `RUN_GENERATE_SCHEMA_TEST=1`일 때만 pytest가 실행한다
- `test/api/test_sources.py` - Fake Repository를 사용하는 Source API 테스트
- `test/api/test_crawl_rules.py` - 크롤링 규칙 생성 API 오류 응답 테스트
- `test/repositories/test_source.py` - Mock Client를 사용하는 실제 Repository 단위 테스트
- `test/services/test_crawl_rule_service.py` - 스키마 검증·상태 전환·URL 재검증 테스트
- `test/integrations/test_url_safety.py` - 공개·사설 IP와 DNS URL 정책 테스트
- `ai_graphs/ingestion_graph/models.py` - 배치용 Source. id와 rule_definition 포함
- `ai_graphs/ingestion_graph/nodes.py` - DB Source 로딩과 CSS 목록 추출
- `seed_konkuk_rule.py` - 로컬 건국대 규칙 저장·활성화 스크립트
- `data/userURL.json` - DB 전환 전 임시 Source 입력. Ingestion은 더 이상 사용하지 않음
- `data/userInfo.md` - DB 전환 전 임시 사용자·추천 Query 입력

## 마지막 상태

- 브랜치: `feat/crawl-rule-api`
- 최근 코드 커밋: `9d1f4ab` (`feat: 크롤링 규칙 생성 API`), `a4cd6ea` (`fix: 외부 URL SSRF 사전 차단`)
- 작업 트리: 기능·보안·HANDOFF 변경을 3개 커밋으로 정리한 clean 상태
- 안전 테스트: `conda run -n infohelper pytest test/api test/repositories test/schemas test/services test/integrations test/ingestion_graph -q` → `79 passed, 1 warning`
- 문법·diff 검사: `python -m compileall`과 `git diff --check` 통과
- 외부 연동 테스트: 이번 세션에서는 실제 Supabase·Gemini·Crawl4AI 호출을 실행하지 않음
- 다음 세션 시작 문구: `docs/HANDOFF.md 읽고 Crawl4AI redirect·브라우저 요청 SSRF 가드부터 이어서 진행해줘`
