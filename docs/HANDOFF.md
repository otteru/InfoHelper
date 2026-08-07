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
  - Execution Role에 ECR Pull·CloudWatch Logs 권한 연결
  - Task Role에 SES `SendEmail` 최소 권한 연결
- [x] SSM Parameter Store Secret 구성
  - Google API Key와 Supabase Secret Key를 `SecureString`으로 저장
  - Execution Role에 해당 Parameter를 읽는 `ssm:GetParameters` 권한 연결
- [x] Fargate용 Docker 이미지 ECR Push
  - 로컬 이미지 플랫폼: `linux/amd64`
  - ECR 태그: `a3d9b7ffe40b7b228c8b5de8ec2d8c57eea60d33`
  - Digest: `sha256:19de1df39ee40b079634b4246c3e742ea7d998c54439202c54fe696cff53e931`
- [x] ECS Task Definition 코드 작성 및 검수
  - Fargate, `awsvpc`, Linux `X86_64`, 1 vCPU·2GB 메모리 설정
  - ECR 이미지 URI에 Commit SHA 태그 적용
  - 일반 환경 변수와 SSM Secret 주입 구성
  - Execution Role·Task Role·CloudWatch Logs 연결
  - Python 문법 검사와 `git diff --check` 통과
  - 실제 `pulumi preview` 결과: Task Definition 1개 생성, 기존 21개 리소스 변경 없음

## 진행 중인 작업

- [ ] ECS Task Definition 배포
  - 진행 상황: 코드 작성과 Preview 완료, 아직 `pulumi up`은 실행하지 않음
  - 대상 변경: `aws:ecs:TaskDefinition app-task-definition` 1개 생성
  - 기존 리소스: 21개 unchanged, 수정·교체·삭제 없음
  - 다음 단계: `pulumi up` 후 Task Definition ARN Output 확인
- [x] ECS Task Definition 구성 커밋
  - 커밋: `12a4a63 feat: ECS Task Definition 구성`
  - 변경 내용: `imageTag` 설정, Task Definition 생성 함수와 메인 조립 코드
- [ ] 추천 점수 품질 조정
  - 현재 연결 검증을 위해 최종 추천 기준을 `total_score >= 0.6`으로 사용
  - 실제 추천 품질을 검토한 뒤 기준 또는 점수식 개선 필요

## 다음에 해야 할 작업

1. AWS SSO와 프로젝트 환경을 준비한다.

   ```bash
   conda activate infohelper
   export AWS_PROFILE=infohelper
   aws sso login --profile infohelper
   cd infra
   ```

2. 변경 계획을 한 번 더 확인하고 Task Definition을 배포한다.

   ```bash
   pulumi preview
   pulumi up
   pulumi stack output ecs_task_definition_arn
   ```

3. 배포된 Task Definition으로 Fargate Task를 한 번 수동 실행한다.
   - Public Subnet 2개와 ECS Task Security Group 사용
   - Public IP 할당 활성화
   - 실행 후 CloudWatch Logs에서 다음 항목 확인
     - ECR 이미지 Pull 성공
     - SSM Secret 주입 성공
     - Supabase·Google API 호출 성공
     - SES 발송 성공
     - 프로세스 정상 종료
4. 수동 실행 결과를 확인한 뒤 EventBridge Scheduler 실행 Role과 하루 1회 Schedule을 구성한다.
5. 이후 GitHub Actions의 PR Preview·배포와 AWS OIDC 인증을 구성한다.

## 주의사항

- Task Definition은 실행 설계도이므로 `pulumi up`만으로 컨테이너가 실행되지는 않음
- 로컬 AWS 인증은 `AWS_PROFILE=infohelper`와 SSO를 사용하고 Access Key를 저장하지 않음
- ECS 컨테이너에서는 로컬 SSO가 아니라 IAM Task Role을 사용함
- `.env`, API Key, Supabase Secret Key, AWS 인증정보를 출력하거나 커밋하지 않음
- `Pulumi.dev.yaml`의 Secret 값은 Pulumi 암호문 상태를 유지해야 함
- ECR은 `IMMUTABLE`이므로 같은 태그를 새로운 이미지에 다시 Push할 수 없음
- Dockerfile이나 애플리케이션 코드가 바뀌면 이미지를 다시 빌드·Push하고 `imageTag`를 새 Commit SHA로 변경해야 함
- SES Identity의 Pulumi 논리 이름 `sender_identity`를 변경하면 Import된 리소스 교체 문제가 생길 수 있음
- SES Identity는 `protect=True`이므로 의도하지 않은 삭제·교체를 피해야 함
- SSM Secret은 ECS Task **Execution Role**이 Task 시작 전에 조회함
- SES 호출은 컨테이너 애플리케이션이 ECS Task **Task Role**로 수행함
- `main.py` 실행은 실제 크롤링·Gemini·Supabase·SES 요청을 발생시킴
- `data/userInfo.md`가 Docker 이미지에 포함되므로 ECR을 Private으로 유지하고 개인정보 취급에 주의
- Supabase 적용 완료 migration은 수정하지 않고 새 migration을 추가함
- `supabase db reset --linked`는 원격 DB를 초기화할 수 있으므로 실행하지 않음
- `test/mvp1/requests_test.py`는 import 시 실제 네트워크 요청을 실행하므로 전체 `pytest` 실행을 피함
- 프로젝트 규칙상 `main`/`master` 브랜치에 직접 Push하지 않음

## 관련 파일

- `infra/__main__.py` - Pulumi 설정 로딩, 리소스 조립, Stack Output
- `infra/network.py` - VPC, Public Subnet, Route, Security Group
- `infra/iam.py` - ECS Execution Role, Task Role, IAM 정책
- `infra/ecs.py` - ECS Cluster, Log Group, Task Definition
- `infra/ssm_parameters.py` - SSM `SecureString` Parameter
- `infra/Pulumi.dev.yaml` - `dev` Stack 설정과 암호화된 Secret
- `Dockerfile` - Python 3.12·Chromium 기반 실행 이미지
- `main.py` - 실제 배치 실행 진입점
- `delivery/` - 이메일 생성·SES 발송·중복 발송 방지
- `supabase/migrations/` - 원격 DB 스키마 migration
- `docs/HANDOFF.md` - 현재 작업 인계 문서

## 마지막 상태

- 브랜치: `feat/deployment-setup`
- 마지막 기능 커밋: `12a4a63 feat: ECS Task Definition 구성`
- 원격 상태: `origin/feat/deployment-setup`보다 2커밋 앞섬, Push하지 않음
- Pulumi 실제 배포 상태: 21개 리소스 관리 중, Task Definition은 아직 미배포
- 마지막 Pulumi Preview: Task Definition 1개 생성, 21개 unchanged
- 정적 검증: Python 컴파일 및 `git diff --check` 통과
- 애플리케이션 테스트: 이번 Task Definition 작업 후 다시 실행하지 않음
- 다음 세션 시작 문구: `docs/HANDOFF.md 읽고 ECS Task Definition 배포부터 이어서 진행해줘`
