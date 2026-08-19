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

## 진행 중인 작업

- [ ] 사이트별 크롤링 규칙 설계
  - 현재 `crawl_source_page()`가 상세 공지 링크를 `"artclView.do"`로 하드코딩함
  - 다른 사이트를 등록해도 현재 구조에서는 상세 공지를 찾을 수 없음
  - 사용자·구독보다 먼저 Source를 실제 크롤링 가능한 설정 단위로 완성하기로 결정
- [ ] 사용자·구독 관리
  - `users`와 `sources`의 다대다 관계를 `subscriptions`로 구성할 예정
  - 사이트별 크롤링 규칙과 DB 기반 Ingestion 연결 이후 진행

## 다음에 해야 할 작업

1. 사이트별 크롤링 규칙을 Source 모델에 추가한다.
   - MVP 후보: `detail_url_pattern`, `is_active`
   - `detail_url_pattern`은 상세 공지 URL 판별에 사용한다.
   - CSS selector나 사이트별 전용 파서는 실제 필요가 생길 때 확장한다.
2. Source 스키마, migration, Repository, API 테스트에 크롤링 규칙을 반영한다.
3. Ingestion의 `load_sources()`를 `data/userURL.json` 대신 `sources` 테이블 조회로 변경한다.
4. `"artclView.do"` 하드코딩을 Source별 `detail_url_pattern` 사용으로 변경한다.
5. 필요하면 Source 단건·목록 조회와 활성화 상태 변경 API를 추가한다.
6. `users` 테이블/API를 설계한다.
7. `subscriptions(user_id, source_id)` 관계 테이블/API를 설계한다.
8. 이후 `data/userInfo.md`와 `RECIPIENT_EMAIL`을 사용자·추천 설정 DB 조회로 전환한다.

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
- Supabase CLI는 프로젝트 루트에서 실행하고 Docker Desktop이 필요하다.
- `supabase db reset`은 로컬 DB를 초기화한다. 원격 DB를 지우는 `--linked`를 붙이지 않는다.
- `.env`, `.env.local`, Supabase Secret Key, API key, AWS 인증정보를 커밋하지 않는다.
- 루트 `main.py`는 실제 크롤링·Gemini·Supabase·SES 요청을 실행한다.
- `test/mvp1/requests_test.py`는 import 시 네트워크 요청을 실행하므로 전체 `pytest`는 피한다.
- 현재 Ingestion은 `data/userURL.json`을 읽고 상세 링크를 `"artclView.do"`로 판별한다.
- 기존 `notice_chunks.source_id`는 문자열이고 신규 `sources.id`는 UUID이므로 연결 전 migration 전략이 필요하다.
- 테스트 시 Requests 의존성 불일치 경고와 Starlette `TestClient`의 httpx 사용 중단 예정 경고가 남아 있다.
- 프로젝트 규칙상 `main`/`master` 브랜치에 직접 Push하지 않는다.

## 관련 파일

- `app/main.py` - FastAPI 애플리케이션 진입점
- `app/api/router.py` - API v1 라우터 조립
- `app/api/endpoints/sources.py` - Source 등록 엔드포인트와 Repository 주입
- `app/api/dependencies.py` - Supabase와 Source Repository dependency
- `app/schemas/source.py` - Source 요청·응답 스키마
- `app/repositories/source.py` - SourceRepository Protocol과 Supabase 구현
- `app/exceptions.py` - Source 중복 URL 도메인 오류
- `integrations/clients.py` - Gemini·Supabase 공통 클라이언트 생성
- `supabase/migrations/20260814051424_create_sources.sql` - sources 테이블 migration
- `test/api/test_sources.py` - Fake Repository를 사용하는 Source API 테스트
- `test/repositories/test_source.py` - Mock Client를 사용하는 실제 Repository 단위 테스트
- `ai_graphs/ingestion_graph/models.py` - 현재 배치용 Source 모델
- `ai_graphs/ingestion_graph/nodes.py` - JSON Source 로딩과 하드코딩된 링크 판별 로직
- `data/userURL.json` - DB 전환 전 임시 Source 입력
- `data/userInfo.md` - DB 전환 전 임시 사용자·추천 Query 입력

## 마지막 상태

- 브랜치: `feat/fastapi-user-source-subscription`
- 마지막 기능 커밋: `8505b89 feat: 공지 사이트 저장 API 연결 및 중복 처리`
- 원격 동기화: 현재 브랜치와 upstream이 `0 ahead / 0 behind`
- 작업 트리: clean
- 안전 테스트: `pytest test/api test/repositories -q` → `11 passed`, 경고 1개
- 컴파일: `python -m compileall -q app test/api test/repositories` 통과
- 공백 검사: `git diff --check` 통과
- 로컬 통합 검증: `POST /api/v1/sources` → `201 Created`, Table Editor 저장 확인
- 다음 세션 시작 문구: `docs/HANDOFF.md 읽고 사이트별 크롤링 규칙 설계부터 이어서 진행해줘`
