[English](README.en.md) | [한국어](README.md)

# InfoHelper

An AI-powered batch service that collects university notices, recommends relevant opportunities based on user interests, and delivers them by email.

## Key Features

- Collects university notices with Crawl4AI
- Generates personalized recommendations with Gemini and vector search
- Stores and retrieves notice chunks with Supabase pgvector
- Prevents duplicate emails by tracking delivery history
- Sends recommendation emails through Amazon SES
- Runs automatically each day with EventBridge Scheduler and ECS Fargate

## Architecture

![InfoHelper AWS batch service architecture](docs/images/infohelper_architecture_eng.png)

The application runs through the following workflow:

```text
EventBridge Scheduler
→ ECS Fargate Standalone Task
→ Collect university notices
→ Store and search data in Supabase
→ Generate recommendations with Gemini
→ Send email through Amazon SES
→ Exit the task
```

The AWS infrastructure is managed with Pulumi and includes:

- A private ECR repository with immutable commit SHA image tags
- Two public subnets across separate Availability Zones
- A security group with no inbound access and outbound HTTP/HTTPS only
- Secret injection through AWS Systems Manager Parameter Store
- Separate ECS Task Execution Role and Task Role
- Container log collection with Amazon CloudWatch Logs

## Tech Stack

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

## Local Setup

The project runs in the Miniconda `infohelper` environment.

```bash
conda activate infohelper
pip install -e ".[dev]"
python main.py
```

Create a `.env` file with the following environment variables before running the application:

```dotenv
GOOGLE_API_KEY=
SUPABASE_PROJECT_ID=
SUPABASE_SECRET_KEY=
AWS_REGION=us-east-1
SES_SENDER_EMAIL=
RECIPIENT_EMAIL=
```

> `python main.py` performs real crawling, external API calls, database writes, and email delivery.

## Docker

```bash
docker build --platform linux/amd64 -t info-helper .
docker run --env-file .env info-helper
```

## Infrastructure Deployment

```bash
conda activate infohelper
export AWS_PROFILE=infohelper
aws sso login --profile infohelper
cd infra
pulumi preview
pulumi up
```

AWS credentials and API keys must never be stored in source code or committed to Git.

## Tests

```bash
pytest test/delivery -q
```

`test/mvp1/requests_test.py` performs real network requests during import, so use caution when running the full test suite.

## Documentation

- [Project notes (Korean)](docs/Project.md)
- [Current handoff (Korean)](docs/HANDOFF.md)
