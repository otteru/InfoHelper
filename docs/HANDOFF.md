# 작업 인계 문서

## 완료된 작업

- [x] Ingestion Graph MVP 구현
  - Crawl4AI 배치 크롤링과 URL별 실패 격리
  - 본문 1,000자 청크 분할
  - Gemini `gemini-embedding-2` 1,536차원 임베딩 생성
  - Supabase `(notice_id, chunk_index)` upsert와 오래된 tail 청크 삭제
- [x] Recommendation Graph MVP 구현
  - `data/userInfo.md`의 YAML query와 Markdown 프로필 분리
  - query별 임베딩과 `match_notice_chunks` RPC 검색
  - 유사도 `0.65` 미만 청크 제외
  - `notice_id` 기준 후보 통합
  - 최고 유사도 80% + query coverage 20%로 점수 계산
  - 최종 추천 기준을 현재 `total_score >= 0.6`으로 적용
- [x] Graph 공통 의존성 주입 구조 적용
  - `GraphContext`로 Gemini·Supabase 클라이언트 공유
  - `main.py`가 Context를 한 번 생성해 두 Graph에서 재사용
- [x] 추천 이메일 Delivery 계층 구현
  - 불변 `EmailMessage`
  - HTML·Plain Text Digest 템플릿
  - `EmailSender` Protocol과 SES v2 기반 `SesEmailSender`
  - 추천 0건이면 발송하지 않고 SES 오류는 호출자에게 전파
  - Fake Sender·SES Client를 이용한 단위 테스트 작성
- [x] `main.py` 전체 일일 실행 흐름 연결
  - `Ingestion → Recommendation → Delivery → SES`
  - `recommendations` 결과를 `DeliveryService`에 전달
  - 후보 수와 최종 추천 수 출력
  - `SES_SENDER_EMAIL`, `RECIPIENT_EMAIL`, `AWS_REGION` 환경변수 사용
  - boto3의 동적 반환 타입은 `SESV2Client`로 경계에서 `cast()`
- [x] 실제 로컬 전체 실행 검증
  - 최근 실행 결과: 저장 청크 29개, 크롤링 오류 0개, 추천 후보 14개
  - 기존 기준 `0.7`에서는 최종 추천이 0개여서 메일을 보내지 않음을 확인
  - 연결 검증을 위해 기준을 `0.6`으로 낮춘 뒤 실제 Digest 이메일 수신 확인
- [x] AWS CLI SSO 구성
  - IAM Identity Center 기반 프로필 이름: `infohelper`
  - 기본 워크로드 리전: `us-east-1`
  - 현재 Permission Set: `AdministratorAccess`
  - 로컬에서는 Access Key가 아니라 SSO 임시 자격 증명 사용
- [x] Amazon SES 로컬 발송 검증
  - `us-east-1`에서 이메일 Identity 인증 완료
  - SES CLI `send-email` 성공 및 실제 수신 확인
  - `main.py`를 통한 실제 추천 이메일 수신 확인
- [x] 최소 AWS 배포 구조 결정
  - `EventBridge Scheduler → ECS Fargate Scheduled Task → main.py → SES`
  - 24시간 ECS Service, ALB, API Gateway, SQS, Auto Scaling은 초기 제외
  - NAT Gateway 없이 Public Subnet + Public IP + 인바운드 차단 사용 예정
  - 1인·일 1회 기준 예상 AWS 비용은 월 약 `$1~$3`

## 진행 중인 작업

- [ ] 추천 점수 품질 조정
  - 진행 상황: 실제 후보 최고 점수가 약 `0.6042`여서 메일 연결 검증용으로 기준을 `0.6`까지 낮춤
  - 다음 단계: 실제 추천 내용을 검토하고 `0.6`을 유지할지 점수식·검색 품질을 개선할지 결정
- [ ] 중복 발송 방지
  - 진행 상황: 아직 발송 이력 테이블과 미발송 필터가 없음
  - 다음 단계: Supabase `recommendation_deliveries` 테이블과 성공 후 기록 흐름 설계
- [ ] Docker·Pulumi AWS 배포
  - 진행 상황: 아키텍처와 리전만 결정했으며 Dockerfile, 의존성 명세, Pulumi 프로젝트는 아직 없음
  - 다음 단계: 재현 가능한 Python 의존성부터 정리한 뒤 Docker 이미지 작성

## 다음에 해야 할 작업

1. 현재 미커밋 코드의 작은 정리를 완료한다.
   - `delivery/sender.py` 첫 주석 끝의 `보관s` 오타 수정
   - `test/recommendation_graph/test_graph.py` 경계값 테스트 들여쓰기 정리
   - Supabase 환경변수 이름을 대문자로 통일할지 결정
2. 의존성 명세를 만든다.
   - 현재 저장소에는 `requirements.txt`, `pyproject.toml` 등의 재현 가능한 명세가 없음
   - `my_jupyter_env`의 전체 패키지를 그대로 고정하지 말고 런타임·개발 의존성을 구분
3. Dockerfile과 `.dockerignore`를 작성한다.
   - 컨테이너 명령은 우선 `python main.py`
   - Crawl4AI/Chromium 시스템 의존성 확인
   - Apple Silicon 로컬과 Fargate 아키텍처 불일치를 피하도록 `linux/amd64` 기준 검증
   - `.env`, AWS 설정, Git 파일을 이미지에 포함하지 않음
4. 로컬 Docker 실행을 검증한다.
   - Ingestion·Recommendation·SES까지 실제 실행하기 전 환경변수와 AWS SSO 전달 방식을 확인
5. 중복 발송 방지를 구현한다.
   - 초기 유니크 기준: `(user_id, notice_id, channel)`
   - SES 성공 후에만 이력 저장
   - SES 실패 시 발송 완료로 기록하지 않음
6. Pulumi Python 프로젝트를 만든다.
   - 리전: `us-east-1`
   - VPC, Public Subnet, Internet Gateway, Route Table, Security Group
   - ECR, ECS Cluster, CloudWatch Log Group
   - Task Execution Role, Task Role, Scheduler Role
   - ECS Task Definition과 비활성 상태의 EventBridge Scheduler
7. 비밀 값을 SSM Parameter Store `SecureString`으로 연결한다.
   - `GOOGLE_API_KEY`, Supabase Secret Key
   - AWS Access Key는 저장하지 않고 ECS Task Role 사용
   - 일반 설정은 ECS Task Definition 환경변수로 주입
8. ECR에 이미지를 올리고 Fargate Task를 수동 실행한다.
   - CloudWatch 로그, 외부 네트워크, SES 발송, 프로세스 종료 코드 확인
9. 수동 실행 성공 후 EventBridge Scheduler를 활성화한다.
   - `Asia/Seoul` 타임존으로 하루 1회 실행
10. 실제 사용자에게 발송하기 전에 SES Production access를 신청한다.
   - Sandbox에서는 인증된 수신자에게만 발송 가능

## 주의사항

- 실행 환경은 Miniconda `my_jupyter_env`임
- `.env`와 API Key, Supabase Secret Key를 출력하거나 커밋하지 않음
- 로컬 AWS 인증은 `AWS_PROFILE=infohelper`를 사용하고 Access Key를 `.env`에 저장하지 않음
- ECS에서는 SSO나 Access Key가 아니라 IAM Task Role을 사용해야 함
- SES Identity, Sandbox 상태, Production access는 리전별이며 현재 기준 리전은 `us-east-1`임
- 현재 SSO Permission Set은 `AdministratorAccess`이므로 인프라 구축 후 최소 권한으로 축소해야 함
- 현재 추천 기준 `0.6`은 실제 메일 연결 검증을 위해 낮춘 값임
- 추천이 0개이면 `DeliveryService`가 정상적으로 발송을 생략함
- 발송 이력이 없어 동일 공지가 재실행 시 중복 발송될 수 있음
- `notice_chunks.embedding`과 query embedding은 모두 `gemini-embedding-2`, 1,536차원을 유지해야 함
- `match_notice_chunks` SQL 정의는 저장소 밖 Supabase에 있음
- `main.py` 실행은 실제 크롤링·Gemini·Supabase·SES 요청을 발생시킴
- `test/mvp1/requests_test.py`는 import 시 실제 네트워크 요청을 하므로 전체 `pytest` 실행을 피함
- `RequestsDependencyWarning`, `LangChainPendingDeprecationWarning`은 현재 테스트 실패 원인이 아님
- 다음 파일 삭제와 `AGENTS.md` 변경은 기존 사용자 변경이므로 임의 복구·커밋하지 않음
  - `ai_graphs/ingestion_graph/prompt.py`
  - `crawl_and_embed.py`
  - `rag_answer.py`
- `delivery/sender.py` 첫 주석의 `보관s`는 기존 미커밋 변경이며 아직 수정하지 않음
- 프로젝트 규칙상 `main`/`master` 브랜치에 직접 push하지 않음

## 관련 파일

- `main.py` - 현재 전체 로컬 일일 실행 진입점
- `ai_graphs/shared/context.py` - Graph 공통 Runtime Context
- `ai_graphs/shared/clients.py` - Gemini·Supabase 클라이언트 생성
- `ai_graphs/ingestion_graph/nodes.py` - 크롤링·임베딩·Supabase 저장
- `ai_graphs/recommendation_graph/nodes.py` - 검색·후보 통합·최종 추천 및 `0.6` 기준
- `ai_graphs/recommendation_graph/graph.py` - Recommendation Graph 연결
- `delivery/models.py` - 불변 `EmailMessage`
- `delivery/templates.py` - HTML·Plain Text Digest 렌더링
- `delivery/service.py` - 이메일 조립과 추천 0건 미발송 정책
- `delivery/sender.py` - SES v2 요청 구현체
- `test/delivery/` - Delivery 템플릿·Sender·Service 테스트
- `test/recommendation_graph/test_graph.py` - Recommendation Graph 및 점수 경계 테스트
- `docs/HANDOFF.md` - 현재 인계 문서

## 마지막 상태

- 브랜치: `main`
- 마지막 커밋: `e58300d feat: 추천 이메일 Delivery 계층 구현`
- 원격 상태: `origin/main`보다 1커밋 앞섬, push하지 않음
- 실제 실행 상태: 로컬 `main.py` 전체 실행과 추천 이메일 수신 성공
- 테스트 상태: `17 passed, 1 warning`
- 테스트 명령:
  - `conda run -n my_jupyter_env python -m pytest -q test/delivery test/recommendation_graph/test_graph.py test/ingestion_graph/test_nodes.py`
- 미커밋 변경:
  - `AGENTS.md`
  - `ai_graphs/ingestion_graph/prompt.py` 삭제
  - `crawl_and_embed.py` 삭제
  - `rag_answer.py` 삭제
  - `ai_graphs/recommendation_graph/nodes.py` 추천 기준 `0.6`
  - `test/recommendation_graph/test_graph.py` 기준값 테스트 수정
  - `main.py` 전체 Delivery 연결과 최종 추천 로그
  - `delivery/sender.py` 주석 오타
  - `docs/HANDOFF.md` 현재 상태 갱신
