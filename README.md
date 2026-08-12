[한국어](README.md) | [English](README.en.md)

# InfoHelper

사용자 정보와 관심사를 바탕으로 대학교 공지를 수집·추천하고 이메일로 전달하는 AI 배치 서비스입니다.

## 주요 기능

- Crawl4AI 기반 대학교 공지 수집
- Gemini와 Vector Search를 활용한 사용자 맞춤 추천
- Supabase pgvector 기반 공지 청크 저장·검색
- 발송 이력 저장을 통한 이메일 중복 발송 방지
- Amazon SES 기반 추천 이메일 발송
- EventBridge Scheduler와 ECS Fargate 기반 일일 자동 실행

## 아키텍처

![InfoHelper AWS 배치 서비스 아키텍처](docs/images/infohelper_architecture.png)

애플리케이션은 다음 순서로 동작합니다.

```text
EventBridge Scheduler
→ ECS Fargate Standalone Task
→ 대학교 공지 수집
→ Supabase 저장 및 검색
→ Gemini 추천 생성
→ Amazon SES 이메일 발송
→ Task 정상 종료
```

AWS 인프라는 Pulumi로 관리하며, 주요 구성은 다음과 같습니다.

- Private ECR과 불변 Commit SHA 이미지 태그
- 서로 다른 가용영역의 Public Subnet 2개
- 인바운드 없이 HTTP·HTTPS 아웃바운드만 허용하는 Security Group
- SSM Parameter Store 기반 Secret 주입
- 역할이 분리된 ECS Task Execution Role과 Task Role
- CloudWatch Logs 기반 컨테이너 로그 수집

## 기술 스택

![Python](https://img.shields.io/badge/Python_3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?style=flat-square&logo=langchain&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?style=flat-square)
![Google Gemini](https://img.shields.io/badge/Google_Gemini-8E75B2?style=flat-square&logo=googlegemini&logoColor=white)
![Crawl4AI](https://img.shields.io/badge/Crawl4AI-FF6B35?style=flat-square)
![Supabase](https://img.shields.io/badge/Supabase-3FCF8E?style=flat-square&logo=supabase&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![pgvector](https://img.shields.io/badge/pgvector-336791?style=flat-square)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)
![Pulumi](https://img.shields.io/badge/Pulumi-8A3391?style=flat-square&logo=pulumi&logoColor=white)
![AWS](https://img.shields.io/badge/AWS-ECS%20%7C%20ECR%20%7C%20SES%20%7C%20SSM-FF9900?style=flat-square)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=flat-square&logo=githubactions&logoColor=white)

- Language: Python 3.12
- AI Workflow: LangGraph, LangChain, Google Gemini
- Crawling: Crawl4AI
- Database: Supabase PostgreSQL, pgvector
- Cloud: AWS ECS Fargate, ECR, SES, SSM, CloudWatch, EventBridge Scheduler
- Infrastructure as Code: Pulumi
- Container: Docker

## 로컬 실행

Miniconda의 `infohelper` 환경을 사용합니다.

```bash
conda activate infohelper
pip install -e ".[dev]"
python main.py
```

실행 전 `.env`에 다음 환경변수가 필요합니다.

```dotenv
GOOGLE_API_KEY=
SUPABASE_PROJECT_ID=
SUPABASE_SECRET_KEY=
AWS_REGION=us-east-1
SES_SENDER_EMAIL=
RECIPIENT_EMAIL=
```

> `python main.py`는 실제 크롤링, 외부 API 호출, 데이터 저장 및 이메일 발송을 수행합니다.

## Docker 실행

```bash
docker build --platform linux/amd64 -t info-helper .
docker run --env-file .env info-helper
```

## 인프라 배포

```bash
conda activate infohelper
export AWS_PROFILE=infohelper
aws sso login --profile infohelper
cd infra
pulumi preview
pulumi up
```

AWS 인증정보와 API Key는 코드나 Git에 저장하지 않습니다.

## 테스트

```bash
pytest test/delivery -q
```

`test/mvp1/requests_test.py`는 import 시 실제 네트워크 요청을 실행하므로 전체 테스트 실행 시 주의해야 합니다.

## 문서

- [프로젝트 기획](docs/Project.md)
- [작업 인계 문서](docs/HANDOFF.md)
