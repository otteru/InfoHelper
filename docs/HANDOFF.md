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
  - 최고 유사도 80% + query coverage 20%로 점수 계산
  - 현재 최종 추천 기준은 `total_score >= 0.6`
- [x] Graph 공통 의존성 주입 구조 적용
  - `GraphContext`로 Gemini·Supabase 클라이언트 공유
- [x] 추천 이메일 Delivery 계층과 일일 실행 흐름 구현
  - `Ingestion → Recommendation → Delivery → SES`
  - HTML·Plain Text Digest와 SES v2 Sender 구현
  - 추천 0건이면 발송 생략, SES 오류는 호출자에게 전파
  - 추천 개수 제한을 제거해 미발송 추천을 모두 Digest에 포함
- [x] 로컬·Docker 전체 실행과 실제 SES 이메일 수신 검증
  - Docker에서 저장 청크 29개, 크롤링 오류 0개, 추천 후보 15개, 최종 추천 1개 확인
  - 첫 Docker SES 실행은 만료된 SSO 토큰으로 실패했고, `aws sso login --profile infohelper` 후 재실행 성공
- [x] AWS CLI SSO와 SES 로컬 발송 구성
  - AWS 프로필: `infohelper`
  - 리전: `us-east-1`
  - 현재 Permission Set: `AdministratorAccess`
- [x] 최소 AWS 배포 구조 결정
  - `EventBridge Scheduler → ECS Fargate Scheduled Task → main.py → SES`
  - Public Subnet + Public IP, 인바운드 차단, NAT Gateway 제외
- [x] Python·Docker 실행 환경 구성
  - `pyproject.toml`에 Python 3.12와 런타임·개발 의존성 정의
  - `Dockerfile`, `.dockerignore` 작성
  - `linux/amd64` 이미지 `info-helper:local` 빌드 성공
- [x] 추천 이메일 중복 발송 방지 코드 구현
  - Supabase `recommendation_deliveries` 테이블 생성 확인
  - 유니크 기준: `(recipient_email, notice_id, channel)`
  - 다수의 `(recipient_email, notice_id, channel)` 후보를 `find_delivered_pairs` RPC로 일괄 조회
  - 이미 발송된 사용자·공지 쌍을 제외하고 SES 발송
  - SES 성공 후에만 `recommendation_deliveries` upsert
  - SES 실패 시 발송 이력을 저장하지 않음
  - 커밋: `70cc53f feat: 추천 이메일 중복 발송 방지`
- [x] 중복 발송 방지 단위 검증
  - 이미 발송한 공지 제외
  - 미발송 공지 발송 후 이력 저장
  - SES 실패 시 이력 미저장
  - RPC 응답 형식 검증
  - 안전 테스트 `23 passed, 1 warning`, Python 컴파일·wheel 빌드 통과
- [x] Supabase DB 스키마 migration 관리 적용
  - Supabase CLI 초기화와 원격 프로젝트 연결
  - 기존 원격 스키마를 `remote_schema` baseline migration으로 저장
  - `notice_chunks`, `recommendation_deliveries` 테이블과 `match_notice_chunks`, `find_delivered_pairs` RPC를 저장소에서 관리
  - `anon`, `authenticated`, `PUBLIC`의 테이블·Sequence·RPC 권한을 제거하고 `service_role`만 허용
  - `notice_id`, `title`, `url`에 `NOT NULL` 제약 적용
  - 1,536차원 cosine 검색용 HNSW 인덱스 적용
  - migration 5개 모두 원격 DB 적용 및 `LOCAL = REMOTE` 확인
- [x] DB 관련 저장소 정리
  - 중복 SQL 초안 삭제
  - `.DS_Store` 삭제와 `.gitignore` 등록
- [x] 중복 발송 방지 실제 통합 검증
  - 최신 Docker 이미지로 실제 흐름을 2회 실행 완료
  - 1회차 SES 발송과 이력 저장, 2회차 동일 공지 발송 제외 검증 완료
- [x] Pulumi 프로젝트 골격과 초기 AWS 리소스 배포
  - `infra/`에 Python 3.12 기반 Pulumi 프로젝트와 Pulumi Cloud `dev` Stack 생성
  - `pulumi 3.x`, `pulumi-aws 7.x` 의존성과 `us-east-1` Provider 리전 설정
  - Private ECR `info-helper-dev` 생성
    - 이미지 태그 `IMMUTABLE`, AES-256 암호화, `force_delete=False`
  - 기존 SES v2 Email Identity를 `dev` State에 Import
    - Pulumi 논리 이름 `sender_identity`, `protect=True`
    - 발신 이메일은 `sesSenderEmail` Secret config로 관리
  - VPC `10.0.0.0/16` 생성과 DNS support·hostname 활성화
  - Internet Gateway 생성 후 VPC에 연결
  - Pulumi Update #4 성공, 기존 ECR·SES 변경 없이 VPC·Internet Gateway 생성 확인

## 진행 중인 작업

- [ ] 추천 점수 품질 조정
  - 진행 상황: 최고 점수가 약 `0.60`이어서 연결 검증용으로 기준을 `0.6`까지 낮춤
  - 다음 단계: 실제 추천 내용을 검토하고 기준 유지 또는 점수식 개선 결정
- [ ] Pulumi AWS 배포
  - 진행 상황: ECR, SES Identity Import, VPC, Internet Gateway 배포 완료
  - 현재 Pulumi Output: `ecr_repository_url`, `ses_identity_arn`, `vpc_id`
  - 다음 단계: Public Subnet과 Route Table을 정의하고 `0.0.0.0/0 → Internet Gateway` 경로 연결
  - SES 전략: Pulumi는 AWS를 자동 탐색해 get-or-create하지 않으므로, `us-east-1`에 이미 인증된 Identity는 최초 1회 `pulumi import`로 `dev` State에 연결
  - Import 후에는 일반 `aws.sesv2.EmailIdentity` 선언과 `protect=True`로 관리
  - 새로운 Stack·AWS 계정에 Identity가 없으면 동일한 선언이 새 Identity를 생성하며 이메일 인증이 별도로 필요
  - 이후 ECS Task Role에 `ses:SendEmail` 최소 권한을 부여하고 Access Key는 컨테이너에 저장하지 않음

## 다음에 해야 할 작업

1. Public Subnet 수와 가용영역을 결정하고 Subnet을 정의한다.
2. Public Route Table, `0.0.0.0/0 → Internet Gateway` Route, Subnet Association을 정의한다.
3. 인바운드가 없는 ECS Task Security Group과 필요한 아웃바운드 정책을 정의한다.
4. ECS Cluster와 CloudWatch Log Group을 정의한다.
5. Task Execution Role, Task Role, Scheduler Role, ECS Task Definition을 정의한다.
6. `GOOGLE_API_KEY`, `SUPABASE_SECRET_KEY`를 SSM Parameter Store `SecureString`으로 연결한다.
7. ECR 이미지 Push와 Fargate Task 수동 실행을 검증한다.
8. GitHub Actions에서 PR Preview와 `main` 배포를 구성하고 AWS 인증은 OIDC를 사용한다.
9. 수동 실행 성공 후 `Asia/Seoul` 기준 하루 1회 Scheduler를 활성화한다.

## 주의사항

- 실행 환경은 Miniconda `infohelper`, Python 3.12임
- `.env`, API Key, Supabase Secret Key, AWS 인증정보를 출력하거나 커밋하지 않음
- 로컬 AWS 인증은 `AWS_PROFILE=infohelper`를 사용하고 Access Key를 `.env`에 저장하지 않음
- ECS에서는 SSO나 Access Key가 아니라 IAM Task Role을 사용해야 함
- 현재 SSO Permission Set은 `AdministratorAccess`이므로 인프라 구축 후 최소 권한으로 축소해야 함
- 로컬 Pulumi 명령은 `infohelper` Conda 환경과 `AWS_PROFILE=infohelper`를 사용함
- ECR은 `IMMUTABLE`이므로 GitHub Actions에서 `latest` 같은 태그를 재사용하지 않고 Commit SHA 등 고유 태그를 사용해야 함
- ECR은 `force_delete=False`이므로 이미지가 있으면 Repository 삭제가 실패하는 것이 정상임
- SES Identity의 Pulumi 논리 이름은 Import된 State와 동일한 `sender_identity`를 유지해야 함
- SES Identity는 `protect=True`이므로 삭제나 교체가 필요한 경우 보호를 명시적으로 해제해야 함
- `sesSenderEmail`이 Secret config라 이를 사용해 만든 SES ARN Output도 Secret으로 전파됨
- 로컬 Pulumi CLI는 `v3.208.0`으로 동작했으며 SDK는 `3.x` 범위이므로 추후 CLI 업데이트 권장
- `data/userInfo.md`가 Docker 이미지에 포함되므로 ECR은 Private으로 유지하고 개인정보 취급에 주의
- 최신 중복 발송 방지 코드는 기존 `info-helper:local` 이미지에 포함되지 않았을 수 있으므로 반드시 재빌드해야 함
- `recommendation_deliveries`는 RLS가 활성화되어 있으며 backend는 `SUPABASE_SECRET_KEY`를 사용함
- Supabase 스키마와 RPC는 `supabase/migrations/`에서 관리하며 적용된 migration SQL은 수정하지 않고 새 migration을 추가함
- 원격 DB 변경 전 `supabase db push --dry-run`으로 적용 대상을 먼저 확인함
- `supabase db reset --linked`는 원격 DB를 초기화할 수 있으므로 실행하지 않음
- SES 발송 성공 후 DB 저장 전에 프로세스가 중단되면 다음 실행에서 중복 발송될 수 있음. SES와 DB 사이의 분산 트랜잭션 한계임
- 다중 사용자 발송은 순차 처리되며 한 사용자의 SES 오류가 이후 사용자 처리를 중단시킴
- 현재 추천 기준 `0.6`은 이메일 연결 검증을 위해 낮춘 값임
- `main.py` 실행은 실제 크롤링·Gemini·Supabase·SES 요청을 발생시킴
- `notice_chunks.embedding`과 query embedding은 모두 `gemini-embedding-2`, 1,536차원을 유지
- `match_notice_chunks`와 `find_delivered_pairs` SQL 정의는 baseline migration에 포함됨
- `test/mvp1/requests_test.py`는 import 시 실제 네트워크 요청을 하므로 전체 `pytest` 실행을 피함
- `RequestsDependencyWarning`, `LangChainPendingDeprecationWarning`은 현재 테스트 실패 원인이 아님
- 프로젝트 규칙상 `main`/`master` 브랜치에 직접 push하지 않음

## 관련 파일

- `main.py` - 전체 실행 진입점, History·Sender·Service 의존성 주입
- `delivery/models.py` - `DeliveryKey`, `EmailMessage` 불변 모델
- `delivery/history.py` - 발송 이력 Protocol과 Supabase 구현체
- `delivery/service.py` - 중복 제거, 사용자별 발송, 성공 이력 저장 조정
- `delivery/templates.py` - 개수 제한 없는 HTML·Plain Text Digest 렌더링
- `delivery/sender.py` - SES v2 이메일 발송
- `test/delivery/test_history.py` - Supabase History 단위 테스트
- `test/delivery/test_service.py` - 중복 제거·성공 저장·실패 미저장 테스트
- `test/delivery/test_templates.py` - 모든 추천 표시 테스트
- `ai_graphs/shared/context.py` - Gemini·Supabase 공통 클라이언트 Context
- `Dockerfile` - Python 3.12, Crawl4AI·Chromium, 프로젝트 실행 이미지
- `pyproject.toml` - Python 버전과 의존성·패키지 설정
- `infra/Pulumi.yaml` - Pulumi 프로젝트와 Python Runtime 설정
- `infra/Pulumi.dev.yaml` - `dev` Stack 리전·ECR·SES Secret·VPC CIDR 설정
- `infra/pyproject.toml` - Pulumi Python SDK와 AWS Provider 의존성
- `infra/__main__.py` - ECR, SES Identity, VPC, Internet Gateway 정의와 Stack Output
- `supabase/config.toml` - Supabase 로컬 개발·migration 설정
- `supabase/migrations/20260805034940_remote_schema.sql` - 기존 원격 DB 구조 baseline
- `supabase/migrations/20260805041354_restrict_backend_permissions.sql` - backend 전용 권한 제한
- `supabase/migrations/20260805043502_add_notice_chunks_not_null.sql` - 공지 필수 컬럼 제약
- `supabase/migrations/20260805043525_add_notice_chunks_hnsw_index.sql` - cosine HNSW 인덱스
- `supabase/migrations/20260805043956_restrict_default_function_permissions.sql` - 미래 RPC의 PUBLIC 기본 실행 권한 차단
- `docs/HANDOFF.md` - 현재 작업 인계 문서

## 마지막 상태

- 브랜치: `feat/deployment-setup`
- 마지막 작업 커밋: Pulumi AWS 기본 인프라 구성과 배포 인계 갱신
- 원격 상태: `origin/feat/deployment-setup`보다 3커밋 앞섬, push하지 않음
- 테스트 상태: `23 passed, 1 warning`
- 테스트 명령:
  - `conda run -n infohelper python -m pytest -q test/delivery test/recommendation_graph/test_graph.py test/ingestion_graph/test_nodes.py`
- Python 문법·import 컴파일 통과
- `pip wheel --no-deps --no-build-isolation .` 빌드 통과
- Docker 이미지: `info-helper:local`, `linux/amd64`; 최신 커밋 포함 위해 재빌드 필요
- Supabase migration 상태: 5개 모두 원격 적용, `LOCAL = REMOTE`
- Pulumi 상태: `dev` Stack Update #4 성공, ECR·SES Identity·VPC·Internet Gateway 관리 중
- 현재 미커밋 변경 없음
- `*.egg-info/`, `__pycache__/`는 빌드·실행 산출물이므로 `.gitignore`에서 제외
- 이번 세션에서는 애플리케이션 테스트를 다시 실행하지 않았고, Pulumi Preview·Up만 검증함
