# 작업 인계 문서

## 완료된 작업

- [x] Ingestion Graph 기본 구조와 실행 진입점 구성
  - `ai_graphs/ingestion_graph/`에 state, model, graph, node를 분리함
  - Crawl4AI `arun_many()` 배치 크롤링과 URL별 실패 격리를 적용함
  - 공지 본문을 1,000자 청크로 나누고 Gemini 1536차원 임베딩을 생성함
  - `(notice_id, chunk_index)` 기준 Supabase upsert와 오래된 tail 청크 삭제를 구현함
- [x] Graph 공통 의존성 주입 구조 적용
  - `ai_graphs/shared/context.py`의 `GraphContext`를 Ingestion·Recommendation Graph에서 함께 사용함
  - Gemini·Supabase 클라이언트는 root `main.py`에서 생성해 Runtime Context로 주입함
- [x] Ingestion 실행 오류 출력 추가
  - root `main.py`에서 저장된 청크 수와 크롤링 오류를 출력함
- [x] Recommendation 사용자 프로필 형식 구성
  - `data/userInfo.md` 상단 YAML Front Matter에 목적별 추천 query를 추가함
  - Markdown 본문은 자유로운 사용자 문맥으로 유지함
- [x] Recommendation Graph 검색·후보 통합 MVP 구현
  - `load_user_info`가 Markdown 본문과 YAML query를 분리함
  - query마다 Gemini 임베딩을 생성하고 `match_notice_chunks` RPC로 상위 20개 청크를 검색함
  - 유사도 `0.65` 미만 청크를 제외함
  - Supabase 응답을 불변 `RetrievedChunk` 모델로 검증·변환함
  - 동일 공지 청크를 `notice_id`로 통합함
  - 최고 유사도 80%와 query coverage 20%로 후보 점수를 계산함
  - 후보를 `total_score` 내림차순으로 정렬함
- [x] Recommendation Graph와 실행 진입점 구성
  - `START → load_user_info → queries_search → merge_candidates → select_recommendations → END`로 연결함
  - `total_score >= 0.7`인 후보만 최종 `recommendations`로 선정함
  - root `main.py`에 `run_recommendation()`을 추가함
  - 현재 `main()`은 Ingestion 실행 후 Recommendation을 실행함
- [x] Recommendation Graph 테스트 추가
  - Gemini·Supabase를 mock으로 대체해 전체 Graph 흐름을 검증함
  - RPC 필수 필드 누락과 검색 결과 0건 처리를 검증함
  - Recommendation 3개와 Ingestion 3개 테스트가 통과함
- [x] Recommendation Graph 변경을 main 브랜치에 분리 커밋
  - `515040f feat: 사용자 추천 query 메타데이터 추가`
  - `2d21892 feat: Recommendation Graph 후보 검색 구현`
  - `b79a8fd test: Recommendation Graph 워크플로우 검증`
  - `4be2635 feat: Recommendation Graph 실행 진입점 추가`
  - `18da26b feat: Recommendation 최종 선정 기준 추가`
- [x] 이메일 전송과 AWS 배포 방향 결정
  - 이메일은 Recommendation Graph 노드가 아니라 별도 Delivery Service가 담당하기로 함
  - 메일 제공자는 향후 AWS 배포와 연결하기 쉬운 Amazon SES v2를 사용하기로 함
  - 로컬에서 이메일 전송과 DailyJob을 완성한 직후 최소 AWS 배포를 진행하기로 함
  - 초기 배포는 `EventBridge Scheduler → ECS Fargate Scheduled Task → DailyJob → SES` 구조로 결정함
  - 현재 단계에서는 ALB, API Gateway, SQS, Auto Scaling, NAT Gateway를 도입하지 않기로 함
- [x] 추천 이메일 모델과 Digest 템플릿 구현
  - `delivery/models.py`에 불변 `EmailMessage`를 작성함
  - `recipient`, `subject`, `html_body`, `text_body`를 한 이메일 단위로 묶음
  - 최종 `recommendations`의 `title`, `url`, `best_chunk`, `matched_queries`, `total_score`를 템플릿에 사용함
  - 상위 5개 추천을 HTML 카드 형식과 Plain Text 형식으로 렌더링함
  - 이메일 클라이언트 호환성을 위해 테이블 레이아웃과 인라인 CSS를 사용함
  - HTML escape, 반응형 스타일, 추천 0건 안내를 적용함
  - 템플릿 테스트 4개를 추가함
- [x] Delivery 계층 책임 결정
  - `templates.py`: 추천 결과를 이메일 본문으로 변환
  - `models.py`: 완성된 이메일 한 통의 데이터 정의
  - `service.py`: 이메일 조립과 전체 발송 흐름 관리
  - `sender.py`: Amazon SES API 호출 담당
  - 별도 `Candidate` 모델을 우선 도입하지 않고 최종 `recommendations`를 Delivery에 전달하기로 함
- [x] Delivery 이메일 전송 계층과 단위 테스트 구현
  - `EmailSender` Protocol과 SES v2 기반 `SesEmailSender`를 작성함
  - `SESV2Client` 타입은 `TYPE_CHECKING`에서만 import하고 annotation 평가를 지연함
  - `DeliveryService`가 추천 결과로 `EmailMessage`를 조립하고 Sender에 전달함
  - 추천 0건이면 이메일을 전송하지 않음
  - 템플릿·Sender·Service 단위 테스트 10개가 통과함
  - Fake Sender와 Fake SES Client를 사용해 실제 AWS 요청 없이 검증함

## 진행 중인 작업

- [ ] 이메일 전송 MVP 구현
  - 진행 상황: 로컬 Delivery 계층 구현과 단위 테스트를 완료함
  - `SesEmailSender`는 `SESV2Client`를 주입받아 SES v2 `send_email()` 요청을 구성함
  - 미구현 사항: SES Identity 인증, boto3 클라이언트 조립, 실제 테스트 메일 전송, 중복 발송 방지
  - 다음 단계: Amazon SES 서울 리전에서 발신·수신 이메일을 인증함
- [ ] Recommendation 점수 개선
  - 진행 상황: Vector 유사도와 query coverage만 적용됨
  - 다음 단계: 결과 품질을 확인한 뒤 키워드 보정과 메타데이터 필터 필요성을 판단함

## 다음에 해야 할 작업

1. Amazon SES 서울 리전에서 발신·수신 이메일을 인증한다.
   - SES Sandbox에서는 발신자와 수신자 모두 인증이 필요함
2. boto3 SES v2 클라이언트를 생성해 `SesEmailSender`와 조립한다.
   - `boto3.client("sesv2", region_name="ap-northeast-2")`
   - 인증된 발신자 이메일은 환경 설정에서 주입
3. 로컬 `my_jupyter_env`에서 테스트 이메일 한 건을 전송한다.
   - 로컬에서는 AWS CLI Profile을 사용
   - AWS Access Key를 `.env`에 저장하지 않음
4. Supabase에 중복 발송 방지용 `recommendation_deliveries` 테이블을 구성한다.
   - 초기 유니크 기준: `(user_id, notice_id, channel)`
5. 이메일 전송 성공 후에만 발송 이력을 저장하는 Delivery Service를 구현한다.
6. root 실행 흐름을 `DailyJob`으로 분리한다.
   - `IngestionGraph → RecommendationGraph → 미발송 필터 → SES`
   - 한 실행에서 `GraphContext`와 외부 클라이언트를 재사용함
7. 다음 이메일 테스트를 작성한다.
   - 이미 발송한 공지 제외
   - SES 성공 후에만 이력 저장
   - SES 실패 시 발송 완료로 기록하지 않음
8. 로컬 DailyJob 검증 후 Docker 이미지를 작성하고 최소 AWS 배포를 진행한다.
    - ECR
    - ECS Fargate Scheduled Task
    - EventBridge Scheduler
    - CloudWatch Logs
    - IAM Task Role
9. 실제 추천 결과를 보고 아래 값을 조정한다.
   - `SIMILARITY_THRESHOLD = 0.65`
   - query별 `match_count = 20`
   - 최고 유사도 80%, query coverage 20% 가중치
10. 이후 사용자 URL 기반 범용 크롤러를 구현한다.
11. 다중 사용자·다중 출처 단계에서 필요할 때 SQS와 Worker를 도입한다.
12. 채팅 기반 사용자 프로필 업데이트는 범용 크롤러 이후 구현한다.

## 주의사항

- 실행 환경은 Miniconda의 `my_jupyter_env`이며 `python-frontmatter`를 포함한 의존성이 설치되어 있음
- 저장소에는 현재 의존성 명세 파일이 없어 다른 환경에서 재현하려면 별도 정리가 필요함
- `.env`의 `GOOGLE_API_KEY`, `supabase_project_id`, `supabase_secret_key`를 출력하거나 커밋하지 않음
- `notice_chunks.embedding`과 query embedding은 모두 `gemini-embedding-2`, 1536차원을 사용해야 함
- `match_notice_chunks`의 실제 SQL 정의는 저장소에 없으므로 반환 스키마를 Supabase에서 확인해야 함
- `main.py` 실행 시 Ingestion과 Recommendation이 연속으로 실행되어 실제 크롤링·Gemini·Supabase 요청이 발생함
- 현재 키워드 점수, 마감일, 상태, 지원 자격 필터는 구현되지 않음
- 로컬 이메일 전송 계층은 구현했지만 SES Identity 인증과 실제 이메일 전송은 진행하지 않음
- `delivery/sender.py`의 annotation `NameError`는 `from __future__ import annotations`로 해결함
- `mypy_boto3_sesv2`는 개발 환경 타입 검사용이며 현재 `my_jupyter_env`에는 설치되어 있음
- `TYPE_CHECKING`의 타입 import와 `from __future__ import annotations`를 함께 유지해야 함
- `delivery/templates.py`의 `Recommendation`은 현재 `Mapping[str, object]` 타입 별칭임
- 템플릿은 최종 추천 상위 5개만 이메일에 포함함
- `/private/tmp/infohelper-email-preview.html`은 임시 미리보기이며 저장소 파일이 아님
- SES Sandbox에서는 수신 이메일도 같은 리전에서 인증해야 함
- 로컬에서는 AWS CLI Profile을 사용하고 AWS Access Key를 `.env`에 저장하지 않는 방향을 권장함
- ECS 배포 후에는 AWS Access Key 대신 IAM Task Role을 사용함
- 초기 Fargate Task는 실행할 때만 생성하고 완료 후 종료해야 함
- 저비용 MVP에서는 NAT Gateway와 24시간 ECS Service를 생성하지 않음
- AWS 예상 비용은 현재 1인·일 1회 실행 기준 월 약 `$1~$3`이며, 실행 시간에 따라 달라짐
- SES 성공 후 발송 이력 저장 전에 프로세스가 종료되면 중복 메일 가능성이 있으므로 상태 전이 설계가 필요함
- `test/mvp1/requests_test.py`는 import 시 실제 네트워크 요청을 하므로 전체 pytest 실행을 피함
- `RequestsDependencyWarning`, `LangChainPendingDeprecationWarning`은 현재 테스트 실패 원인이 아님
- `AGENTS.md`, 이 인계 문서와 아래 파일 삭제가 미커밋 상태이며 기존 사용자 변경이므로 임의로 복구하거나 커밋하지 않음
  - `ai_graphs/ingestion_graph/prompt.py`
  - `crawl_and_embed.py`
  - `rag_answer.py`
- 프로젝트 규칙에 따라 main 브랜치에 직접 push하지 않음

## 관련 파일

- `main.py` - Ingestion·Recommendation 실행 진입점
- `ai_graphs/shared/context.py` - 공통 Graph Runtime Context
- `ai_graphs/shared/clients.py` - Gemini·Supabase 클라이언트 생성
- `ai_graphs/ingestion_graph/nodes.py` - 크롤링·임베딩·Supabase 저장
- `ai_graphs/ingestion_graph/graph.py` - Ingestion Graph 연결
- `ai_graphs/recommendation_graph/models.py` - `RetrievedChunk`
- `ai_graphs/recommendation_graph/state.py` - `RecommendationState`
- `ai_graphs/recommendation_graph/nodes.py` - 프로필 로드·검색·후보 통합·최종 추천 선정
- `ai_graphs/recommendation_graph/graph.py` - Recommendation Graph 연결
- `data/userInfo.md` - YAML query와 Markdown 사용자 프로필
- `test/ingestion_graph/test_nodes.py` - Ingestion 단위 테스트
- `test/recommendation_graph/test_graph.py` - Recommendation Graph 테스트
- `rag_answer.py` - 기존 `match_notice_chunks` RPC 호출 예시
- `delivery/models.py` - 불변 `EmailMessage`
- `delivery/templates.py` - HTML·Plain Text Digest 렌더링
- `delivery/service.py` - 이메일 조립과 Sender 호출
- `delivery/sender.py` - `EmailSender`와 SES v2 구현체
- `test/delivery/test_templates.py` - Digest 템플릿 테스트
- `test/delivery/test_sender.py` - SES 요청 변환·오류 전달 테스트
- `test/delivery/test_service.py` - 이메일 조립·미전송·오류 전달 테스트
- `jobs/daily_job.py` - 이후 전체 일일 실행 흐름을 추가할 예정

## 마지막 상태

- 브랜치: `main`
- 마지막 커밋: `18da26b feat: Recommendation 최종 선정 기준 추가`
- 원격 상태: `origin/main`과 동기화됨
- 테스트 상태:
  - Delivery 전체: `10 passed`
  - Delivery·Recommendation·Ingestion 관련 테스트: `17 passed, 1 warning`
- 테스트 명령:
  - `conda run -n my_jupyter_env python -m pytest -q test/delivery`
  - `conda run -n my_jupyter_env python -m pytest -q test/delivery test/recommendation_graph/test_graph.py test/ingestion_graph/test_nodes.py`
- 미커밋 변경:
  - `AGENTS.md`
  - `docs/HANDOFF.md`
  - `ai_graphs/ingestion_graph/prompt.py` 삭제
  - `crawl_and_embed.py` 삭제
  - `rag_answer.py` 삭제
  - `delivery/models.py`
  - `delivery/templates.py`
  - `delivery/service.py`
  - `delivery/sender.py`
  - `test/delivery/test_templates.py`
  - `test/delivery/test_sender.py`
  - `test/delivery/test_service.py`
