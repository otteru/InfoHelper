# 작업 인계 문서

## 완료된 작업

- [x] 애플리케이션 MVP 구현 및 Docker 실행 검증
  - Ingestion → Recommendation → Delivery → SES 흐름 구현
  - Supabase 기반 공지 청크 저장·검색과 이메일 중복 발송 방지 적용
  - Docker에서 실제 SES 이메일 발송과 중복 발송 제외 검증 완료
- [x] Supabase migration 관리 적용
  - 원격 스키마 baseline과 후속 migration 5개 적용
  - backend `service_role` 전용 권한, 필수 컬럼 제약, HNSW 인덱스 구성
- [x] Pulumi AWS 실행 인프라 배포
  - Private ECR, SES v2 Email Identity, VPC, Internet Gateway 구성
  - 서로 다른 가용영역의 Public Subnet 2개와 Public Route Table 구성
  - 인바운드 없음, HTTP·HTTPS 아웃바운드만 허용하는 ECS Security Group 구성
  - ECS Cluster, CloudWatch Log Group, Task Definition 구성
  - ECS Task Execution Role과 Task Role 분리
  - SSM Parameter Store에 Google·Supabase Secret 저장
- [x] Fargate용 Docker 이미지 ECR Push
  - 플랫폼: `linux/amd64`
  - ECR 태그: `a3d9b7ffe40b7b228c8b5de8ec2d8c57eea60d33`
  - Digest: `sha256:19de1df39ee40b079634b4246c3e742ea7d998c54439202c54fe696cff53e931`
- [x] ECS Fargate 전체 실행 흐름 검증
  - Public Subnet, ECS Security Group, Public IP로 수동 Task 실행
  - 크롤링·Gemini·Supabase·SES 정상 동작
  - 컨테이너 `Exit code: 0`과 실제 이메일 수신 확인
- [x] EventBridge Scheduler 자동 실행 구성 및 검증
  - Scheduler Execution Role에 `ecs:RunTask`, `iam:PassRole` 최소 권한 구성
  - 매일 08:00 KST 실행: `cron(0 8 * * ? *)`, `Asia/Seoul`, `ENABLED`
  - Scheduler가 ECS Fargate Task를 자동 생성·실행하는 흐름 확인
- [x] GitHub Actions Workflow 코드 작성
  - PR: Python 컴파일, 네트워크 요청 없는 테스트, Pulumi Preview 및 PR 댓글
  - 배포: Feature 브랜치 `workflow_dispatch`, main 병합 Push에서 Pulumi Up
  - 수동 실행은 main을 제외한 모든 브랜치에서만 허용
  - 배포 동시 실행 방지와 PR별 오래된 실행 취소 적용
- [x] GitHub AWS OIDC 인프라 작성 및 로컬 배포
  - GitHub OIDC Provider 생성
  - PR 전용 Preview Role: `ReadOnlyAccess`
  - `dev` Environment 전용 Deploy Role: `ReadOnlyAccess`, `PowerUserAccess`
  - Deploy Role의 `iam:PassRole` 대상을 ECS Task Role 2개와 Scheduler Role로 제한
  - GitHub Role 자신은 수정할 수 없게 해 권한 자체 확장 방지
  - Pulumi Cloud `dev` Stack version 15 배포 성공
  - 신규 리소스 7개 생성, 기존 25개 unchanged, 총 32개 관리
- [x] GitHub Actions/OIDC 코드 커밋
  - `c811ff3 feat: GitHub Actions OIDC 인증 구성`
  - `50ede91 feat: GitHub Actions 검증 및 배포 워크플로 구성`

## 진행 중인 작업

- [ ] GitHub Repository/Environment 설정
  - Repository Variable `AWS_PREVIEW_ROLE_ARN` 등록 필요 여부 확인
  - `dev` Environment와 Variable `AWS_DEPLOY_ROLE_ARN` 등록 필요 여부 확인
  - Repository Secret `PULUMI_ACCESS_TOKEN` 등록 필요 여부 확인
  - `dev` Environment의 Deployment branches는 All branches로 두고 Workflow 조건으로 main 수동 실행을 차단
- [ ] GitHub Actions 실제 PR 검증
  - PR에서 안전 테스트와 OIDC Preview Role 인증 확인
  - Pulumi Preview 결과가 PR에 표시되는지 확인
  - main 병합 후 Deploy Role로 Pulumi Up이 정상 동작하는지 확인
- [ ] 추천 점수 품질 조정
  - 현재 최종 추천 기준은 연결 검증을 위해 `total_score >= 0.6`
  - 실제 추천 품질 검토 후 기준 또는 점수식 개선 필요

## 다음에 해야 할 작업

1. Conda 환경에서 배포 후 Preview를 다시 확인한다.

   ```bash
   conda activate infohelper
   export AWS_PROFILE=infohelper
   cd infra
   pulumi preview
   ```

   - 직전 Preview는 시스템 Python으로 실행되어 `ModuleNotFoundError: No module named 'pulumi'`로 실패함
   - Pulumi 프로그램이나 AWS 리소스 오류가 아니라 Python 실행 환경 문제임
   - 이미 실행한 정적 검사와 안전 테스트 23개는 통과함

2. GitHub 설정값을 등록하거나 등록 상태를 확인한다.

   ```bash
   pulumi stack output github_preview_role_arn
   pulumi stack output github_deploy_role_arn
   ```

   - Repository Variable: `AWS_PREVIEW_ROLE_ARN`
   - `dev` Environment Variable: `AWS_DEPLOY_ROLE_ARN`
   - Repository Secret: `PULUMI_ACCESS_TOKEN`

3. PR Checks에서 Python 테스트와 Pulumi Preview 성공을 확인한다.
4. 실패하면 Actions 로그를 기준으로 Workflow 또는 GitHub 설정을 수정한다.
5. main 병합 후 `Dev Stack 배포` Workflow의 Pulumi Up 성공을 확인한다.
6. 이후 Docker 이미지 빌드·Commit SHA 태깅·ECR Push 자동화를 별도 작업으로 진행한다.

## 주의사항

- `docs/images/infohelper_architecture.png`는 현재 AWS 배치 서비스 구조를 나타내는 최신 아키텍처 이미지임
- GitHub OIDC 리소스와 GitHub Preview/Deploy Role의 권한 변경은 로컬 AWS SSO로 배포함
- GitHub Deploy Role은 자신이나 Preview Role의 IAM 정책을 수정할 수 없음
- `PowerUserAccess`는 IAM 외 AWS 서비스에 넓은 권한을 가지므로 Production 도입 시 Custom Policy로 축소 필요
- GitHub OIDC는 AWS 인증만 해결하며 Pulumi Cloud 인증에는 현재 `PULUMI_ACCESS_TOKEN`이 별도로 필요함
- Workflow의 `dev` Environment 때문에 Deploy Role Trust Policy의 `sub`는 `repo:otteru/InfoHelper:environment:dev`임
- PR Preview Role Trust Policy의 `sub`는 `repo:otteru/InfoHelper:pull_request`임
- `pulumi preview`와 `pulumi up`은 반드시 `infohelper` Conda 환경에서 실행함
- 로컬 AWS 인증은 `AWS_PROFILE=infohelper`와 SSO를 사용하며 Access Key를 저장하지 않음
- `.env`, API Key, Supabase Secret Key, AWS 인증정보를 출력하거나 커밋하지 않음
- `Pulumi.dev.yaml`의 Secret 값은 Pulumi 암호문 상태를 유지함
- ECR은 `IMMUTABLE`이므로 같은 태그를 새 이미지로 덮어쓸 수 없음
- Dockerfile이나 애플리케이션 코드가 바뀌면 이미지 재빌드·Push와 `imageTag` 갱신이 필요함
- `main.py` 실행은 실제 크롤링·Gemini·Supabase·SES 요청을 발생시킴
- `test/mvp1/requests_test.py`는 import 시 실제 네트워크 요청을 실행하므로 전체 `pytest` 실행을 피함
- 프로젝트 규칙상 `main`/`master` 브랜치에 직접 Push하지 않음

## 관련 파일

- `.github/workflows/pr-check.yml` - PR 정적 검사·테스트·Pulumi Preview
- `.github/workflows/pulumi-deploy.yml` - Feature 수동 배포와 main 동기화
- `infra/github_oidc.py` - GitHub OIDC Provider와 Preview/Deploy Role
- `infra/__main__.py` - GitHub OIDC 리소스 조립과 Stack Output
- `infra/Pulumi.dev.yaml` - GitHub Repository·Environment와 dev Stack 설정
- `infra/iam.py` - ECS와 Scheduler IAM Role
- `infra/ecs.py` - ECS Cluster, Log Group, Task Definition
- `infra/scheduler.py` - EventBridge Scheduler와 ECS Fargate Target
- `docs/HANDOFF.md` - 현재 작업 인계 문서

## 마지막 상태

- 브랜치: `feat/github-actions`
- HEAD: `50ede91 feat: GitHub Actions 검증 및 배포 워크플로 구성`
- 원격 상태: `origin/feat/github-actions`보다 로컬이 2커밋 앞섬
- 문서 변경: `docs/HANDOFF.md`, `docs/images/infohelper_architecture.png` 커밋 예정
- Pulumi Cloud `dev` Stack: version 15 배포 성공, 32개 리소스 관리
- 정적 검증: Python 컴파일, Workflow YAML 파싱, 공백 검사 통과
- 테스트: 네트워크 요청 없는 테스트 `23 passed`
- 마지막 Preview: 시스템 Python에 Pulumi SDK가 없어 실패, Conda 환경에서 재실행 필요
- 커밋 상태: OIDC와 Workflow 커밋 완료
- 다음 세션 시작 문구: `docs/HANDOFF.md 읽고 Conda 환경 Pulumi Preview와 GitHub 설정 확인부터 이어서 진행해줘`
