# 작업 인계 문서

## 완료된 작업

- [x] 애플리케이션 MVP 구현 및 Docker 실행 검증
  - Ingestion → Recommendation → Delivery → SES 흐름 구현
  - Supabase 기반 공지 청크 저장·검색과 이메일 중복 발송 방지 적용
  - Docker에서 실제 SES 이메일 발송과 중복 발송 제외 검증 완료
- [x] Supabase migration 관리 적용
  - 원격 스키마 baseline과 후속 migration 5개 적용
  - backend의 `service_role` 전용 권한, 필수 컬럼 제약, HNSW 인덱스 구성
- [x] Pulumi AWS 기본 인프라 배포
  - Pulumi Cloud `dev` Stack과 `us-east-1` Provider 구성
  - Private ECR `info-helper-dev` 구성
    - `IMMUTABLE`, AES-256 암호화, `force_delete=False`
  - 기존 SES v2 Email Identity Import 및 `protect=True` 적용
  - VPC `10.0.0.0/16`, Internet Gateway 구성
  - 서로 다른 가용영역의 Public Subnet 2개 구성
  - Public Route Table과 `0.0.0.0/0 → Internet Gateway` Route 연결
  - 인바운드 없음, HTTP·HTTPS 아웃바운드만 허용하는 ECS Task Security Group 구성
- [x] ECS 실행 기반 리소스 배포
  - ECS Cluster와 CloudWatch Log Group 구성
  - ECS Task Execution Role과 Task Role 분리
  - Execution Role에 ECR Pull·CloudWatch Logs·SSM 조회 권한 연결
  - Task Role에 SES `SendEmail` 최소 권한 연결
- [x] Fargate용 Docker 이미지 ECR Push
  - 플랫폼: `linux/amd64`
  - ECR 태그: `a3d9b7ffe40b7b228c8b5de8ec2d8c57eea60d33`
  - Digest: `sha256:19de1df39ee40b079634b4246c3e742ea7d998c54439202c54fe696cff53e931`
- [x] ECS Task Definition 배포 및 수동 실행 검증
  - Fargate, `awsvpc`, Linux `X86_64`, 1 vCPU·2GB 메모리 설정
  - ECR 이미지, SSM Secret, IAM Role, CloudWatch Logs 연결
  - Public Subnet 2개, ECS Task Security Group, Public IP로 수동 실행
  - 크롤링·Gemini·Supabase·SES 전체 흐름 정상 동작
  - 컨테이너 `Exit code: 0`과 실제 이메일 수신 확인
- [x] EventBridge Scheduler IaC 작성 및 배포
  - Scheduler 전용 Execution Role 생성
    - 신뢰 주체: `scheduler.amazonaws.com`
    - 지정 Task Definition에 대한 `ecs:RunTask`
    - ECS Execution Role과 Task Role에 대한 `iam:PassRole`
  - ECS Fargate Target과 Public Subnet·Security Group·Public IP 연결
  - Pulumi Stack version 12: Scheduler 관련 리소스 3개 생성, 기존 22개 unchanged
  - Pulumi Stack version 13: Schedule 활성화 및 실행 시간 변경 성공
  - 14:07 KST 예약 실행으로 ECS Fargate Task 자동 실행 정상 동작 확인

## 진행 중인 작업

- [ ] Scheduler 운영 실행 시간 변경 배포
  - 코드 설정: `cron(0 8 * * ? *)`, `Asia/Seoul`, `ENABLED`
  - 목표 실행 시간: 매일 08:00 KST
  - 현재 상태: `infra/Pulumi.dev.yaml` 변경 완료, `pulumi up` 미실행
  - 실제 AWS 배포 상태는 아직 매일 14:07 KST
- [ ] 추천 점수 품질 조정
  - 현재 최종 추천 기준은 연결 검증을 위해 `total_score >= 0.6`
  - 실제 추천 품질 검토 후 기준 또는 점수식 개선 필요

## 다음에 해야 할 작업

1. Scheduler 운영 시간 변경을 Preview하고 배포한다.

   ```bash
   conda activate infohelper
   export AWS_PROFILE=infohelper
   aws sso login --profile infohelper
   cd infra
   pulumi preview
   pulumi up
   ```

2. EventBridge Scheduler Console에서 매일 08:00 KST 설정을 확인한다.
3. 다음 예약 실행에서 ECS Task 생성과 `Exit code: 0`을 확인한다.
4. Feature 브랜치를 Push하고 배포 MVP PR을 생성한다.
5. 이후 GitHub Actions의 PR Preview·배포와 AWS OIDC 인증을 구성한다.

## 주의사항

- EventBridge Scheduler에는 현재 별도 DLQ를 구성하지 않음
- Task Definition은 실행 설계도이며, 수동 실행 또는 Scheduler 호출이 있어야 컨테이너가 실행됨
- 로컬 AWS 인증은 `AWS_PROFILE=infohelper`와 SSO를 사용하고 Access Key를 저장하지 않음
- ECS 컨테이너에서는 로컬 SSO가 아니라 IAM Task Role을 사용함
- `.env`, API Key, Supabase Secret Key, AWS 인증정보를 출력하거나 커밋하지 않음
- `Pulumi.dev.yaml`의 Secret 값은 Pulumi 암호문 상태를 유지해야 함
- ECR은 `IMMUTABLE`이므로 같은 태그를 새로운 이미지에 다시 Push할 수 없음
- Dockerfile이나 애플리케이션 코드가 바뀌면 이미지를 다시 빌드·Push하고 `imageTag`를 새 Commit SHA로 변경해야 함
- SES Identity의 Pulumi 논리 이름 `sender_identity`를 변경하지 않음
- SES Identity는 `protect=True`이므로 의도하지 않은 삭제·교체를 피해야 함
- SSM Secret은 ECS Task **Execution Role**이 Task 시작 전에 조회함
- SES 호출은 컨테이너 애플리케이션이 ECS Task **Task Role**로 수행함
- Scheduler Execution Role은 `ecs:RunTask`와 두 ECS Role에 대한 `iam:PassRole`을 사용함
- `main.py` 실행은 실제 크롤링·Gemini·Supabase·SES 요청을 발생시킴
- `data/userInfo.md`가 Docker 이미지에 포함되므로 ECR을 Private으로 유지하고 개인정보 취급에 주의
- Supabase 적용 완료 migration은 수정하지 않고 새 migration을 추가함
- `supabase db reset --linked`는 원격 DB를 초기화할 수 있으므로 실행하지 않음
- `test/mvp1/requests_test.py`는 import 시 실제 네트워크 요청을 실행하므로 전체 `pytest` 실행을 피함
- 프로젝트 규칙상 `main`/`master` 브랜치에 직접 Push하지 않음

## 관련 파일

- `infra/__main__.py` - Pulumi 설정 로딩과 전체 리소스 조립
- `infra/network.py` - VPC, Public Subnet, Route, Security Group
- `infra/iam.py` - ECS Role과 Scheduler Execution Role 및 IAM 정책
- `infra/ecs.py` - ECS Cluster, Log Group, Task Definition
- `infra/scheduler.py` - EventBridge Scheduler와 ECS Fargate Target 설정
- `infra/ssm_parameters.py` - SSM `SecureString` Parameter
- `infra/Pulumi.dev.yaml` - `dev` Stack 설정과 암호화된 Secret
- `Dockerfile` - Python 3.12·Chromium 기반 실행 이미지
- `main.py` - 실제 배치 실행 진입점
- `delivery/` - 이메일 생성·SES 발송·중복 발송 방지
- `supabase/migrations/` - 원격 DB 스키마 migration
- `docs/HANDOFF.md` - 현재 작업 인계 문서

## 마지막 상태

- 브랜치: `feat/deployment-setup`
- 마지막 기능 커밋: `cd87dde feat: EventBridge Scheduler 자동 실행 구성`
- 원격 상태: `origin/feat/deployment-setup`보다 로컬 커밋이 앞서며 아직 Push하지 않음
- Pulumi Cloud `dev` Stack: version 13 배포 성공, 총 25개 리소스 관리
- 실제 EventBridge Schedule: `info-helper-dev-daily`, `ENABLED`, 매일 14:07 KST
- 로컬 운영 시간 설정: 매일 08:00 KST, 아직 `pulumi up` 미실행
- 자동 실행 상태: 14:07 예약 호출로 ECS Fargate Task 자동 실행 정상 동작 확인
- 정적 검증: Python 컴파일과 `git diff --check` 통과
- 린트·타입 검사: 현재 `infohelper` 환경에 `ruff`, `mypy` 미설치
- 다음 세션 시작 문구: `docs/HANDOFF.md 읽고 Scheduler 08:00 운영 시간 배포부터 이어서 진행해줘`
