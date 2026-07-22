# 작업 인계 문서

## 완료된 작업

- [x] 1차 RAG PoC 구조 점검
  - 공지 크롤링, Gemini 임베딩, Supabase 저장, 유사도 검색·답변 스크립트의 존재를 확인함
- [x] Crawl4AI 기반 통합 테스트 작성 및 실행
  - `userURL.json`의 URL을 Crawl4AI로 크롤링해 HTML·Markdown 반환을 검증함
  - `python3 -m pytest -s test/mvp2/crawl4ai_test.py` 통과를 사용자가 확인함
- [x] Ingestion Graph 골격 구현
  - 기존 `graph/`를 `ai_graphs/ingestion_graph/`로 이전함
  - `models.py`에 `Source`, `NoticeTarget`, `Notice`를 분리해 순환 import를 제거함
  - `state.py`에 최소 `IngestionState`를 정의함
  - `graph.py`에 노드와 edge를 연결하고 `compile()`함
  - `main.py`에 `await graph.ainvoke({})` 실행 진입점을 작성함
- [x] Ingestion Graph 실행 확인
  - 목록 페이지 1개와 상세 공지 5개를 Crawl4AI 0.9.0으로 성공적으로 크롤링함
  - Gemini 임베딩 직전 `GOOGLE_API_KEY` 누락으로 중단됨
  - Supabase 저장은 시작되지 않았으므로 이번 실행으로 생성된 DB 데이터는 없음
- [x] 이전 변경사항 커밋
  - `fix: Gemini API 키 환경 변수 통일`
  - `feat: 크롤링 규칙 생성 워크플로우 골격`
  - `test: Crawl4AI 공지 페이지 크롤링 검증`
  - `chore: 개발 환경 설정 정리`

## 진행 중인 작업

- [ ] Ingestion Graph 안정화 및 실제 Supabase 저장 검증
  - 진행 상황: 크롤링·공지 후보 추출까지 동작, 임베딩·저장은 미검증
  - 다음 단계: `.env`의 `GOOGLE_API_KEY`를 확인한 뒤 공지 1개로 임베딩·Supabase 저장을 검증

## 다음에 해야 할 작업

1. `ingestion_graph`의 보조 함수를 책임별 파일로 분리한다.
   - `crawlers.py`: Crawl4AI 실행
   - `normalizers.py`: CrawlResult → Notice 변환
   - `repositories.py`: Supabase 조회·저장
   - `embeddings.py`: Gemini 임베딩 생성
2. Ingestion Graph의 구조적 문제를 수정한다.
   - Supabase·Gemini 클라이언트를 노드마다 만들지 않고 runtime context로 주입
   - 공지마다 브라우저를 새로 만들지 않고 `AsyncWebCrawler` 재사용
   - `upsert_to_vectorDB`의 실제 `insert`를 DB unique constraint와 `upsert`로 변경
   - `notice_id + chunk_index` 등 chunk 중복 방지 키를 설계
   - `saved_count`, `deadline`, 오류 수집을 정리
   - `row["notice_id"]`의 Pylance 타입 경고를 안전한 `notice_id` 반환으로 수정
3. `ai_graphs/recommendation_graph/`를 생성한다.
   - 사용자 프로필과 새 공지를 매칭해 추천 후보를 만드는 Graph
   - 실제 메일 발송은 Graph와 분리된 email service/worker가 담당하도록 설계
4. Ingestion·Recommendation Graph가 안정된 뒤 FastAPI API와 Worker/큐 구조를 설계한다.

## 주의사항

- `.env`에 `GOOGLE_API_KEY`, `supabase_project_id`, `supabase_secret_key`가 필요하다. 값은 출력·커밋하지 않는다.
- 현재 `upsert_to_vectorDB`라는 이름과 달리 저장 함수는 `insert()`를 사용한다. 재시도·동시 실행 시 중복 저장될 수 있다.
- `test/mvp2/test.md`는 테스트 결과물이며 `.gitignore`에 등록되어 있다.
- `test/mvp1/requests_test.py`는 import 시 실제 네트워크 요청을 수행하므로 전체 `pytest` 수집을 깨뜨릴 수 있다.
- `RequestsDependencyWarning`, `LangChainPendingDeprecationWarning`은 최근 실행 중단의 원인이 아니었다.
- `graph/` 삭제와 `ai_graphs/` 추가는 아직 커밋되지 않았다.

## 관련 파일

- `ai_graphs/ingestion_graph/models.py` - Source, NoticeTarget, Notice 도메인 모델
- `ai_graphs/ingestion_graph/state.py` - IngestionState
- `ai_graphs/ingestion_graph/nodes.py` - 크롤링·중복 제외·공지 변환·임베딩·저장 노드
- `ai_graphs/ingestion_graph/graph.py` - Ingestion Graph edge 연결
- `ai_graphs/ingestion_graph/main.py` - Graph 실행 진입점
- `userURL.json` - 임시 크롤링 출처 목록
- `crawl_and_embed.py` - 1차 MVP의 원본 임베딩·저장 구현
- `Project.md` - 프로젝트 목표와 데이터 필드 초안

## 마지막 상태

- 브랜치: `main`
- 마지막 커밋: `f124c2c chore: 개발 환경 설정 정리`
- 원격 상태: `origin/main`과 동기화됨
- 작업 트리: `graph/` 삭제와 `ai_graphs/`, `HANDOFF.md` 추가가 미커밋 상태
- 실행 상태: Crawl4AI 크롤링 성공, `GOOGLE_API_KEY` 누락으로 Gemini 임베딩 전 중단
