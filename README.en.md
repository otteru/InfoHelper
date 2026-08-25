[English](README.en.md) | [한국어](README.md)

# InfoHelper

InfoHelper collects information from university notice sites registered by users, recommends notices that match their interests, and delivers them by email.

The project currently operates an AI batch pipeline on AWS and is expanding a FastAPI-based management API for notice sources and site-specific crawl rules.

## Key Features

- Collects university notices with Crawl4AI
- Generates personalized recommendations with Gemini and vector search
- Stores and retrieves notice chunks with Supabase pgvector
- Prevents duplicate emails by tracking delivery history
- Sends recommendation emails through Amazon SES
- Runs automatically each day with EventBridge Scheduler and ECS Fargate
- Registers notice sources and handles duplicate URLs through FastAPI

## Development Status

Completed:

- Ingestion → Recommendation → Delivery → SES batch pipeline
- Pulumi-based AWS infrastructure and GitHub Actions deployment
- `GET /api/v1/health`
- `POST /api/v1/sources`
- Supabase-backed Source persistence layer
- Database table for storing site-specific crawl rules

In progress:

- Validation and storage of AI-generated Crawl4AI CSS extraction rules
- Crawl-rule versioning and runtime health management
- Loading Sources and crawl rules from the database in the Ingestion pipeline
- User and subscription-based personalization settings

> The Ingestion pipeline currently reads `data/userURL.json` and uses a site-specific link-matching rule. Automatic analysis of arbitrary notice sites is still under development.

## Architecture

### Management API

```text
User
→ FastAPI
→ Source registration and validation
→ Supabase PostgreSQL
```

### Batch Pipeline

![InfoHelper AWS batch service architecture](docs/images/infohelper_architecture_eng.png)

```text
EventBridge Scheduler
→ ECS Fargate Standalone Task
→ Collect notices with Crawl4AI
→ Store data and run vector search in Supabase
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
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=flat-square&logo=pydantic&logoColor=white)
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
- API: FastAPI, Uvicorn, Pydantic
- AI Workflow: LangGraph, LangChain, Google Gemini
- Crawling: Crawl4AI
- Database: Supabase PostgreSQL, pgvector
- Cloud: AWS ECS Fargate, ECR, SES, SSM, CloudWatch, EventBridge Scheduler
- Infrastructure as Code: Pulumi
- Container: Docker

## Local Development

The project uses the Miniconda `infohelper` environment.

```bash
conda activate infohelper
pip install -e ".[dev]"
```

Docker Desktop is required when using the local Supabase stack.

```bash
supabase start
supabase migration up --local
```

### Run FastAPI

```bash
uvicorn app.main:app --reload --env-file .env.local
```

Available endpoints:

```text
GET  /api/v1/health
POST /api/v1/sources
```

### Run the Batch Pipeline

```bash
python main.py
```

> `python main.py` performs real crawling, Gemini calls, Supabase writes, and email delivery.

## Environment Variables

```dotenv
GOOGLE_API_KEY=

# Use either SUPABASE_URL or SUPABASE_PROJECT_ID.
SUPABASE_URL=
SUPABASE_PROJECT_ID=
SUPABASE_SECRET_KEY=

AWS_REGION=us-east-1
SES_SENDER_EMAIL=
RECIPIENT_EMAIL=
```

Never commit `.env`, `.env.local`, API keys, or AWS credentials to Git.

## Docker

The current Docker image targets the AWS batch runtime. Recent changes to the shared client package layout have not yet been reflected in the Dockerfile, so use the Python commands above for local execution.

## Infrastructure Deployment

```bash
conda activate infohelper
export AWS_PROFILE=infohelper
aws sso login --profile infohelper
cd infra
pulumi preview
pulumi up
```

## Tests

Run tests that do not make external network requests with:

```bash
pytest \
  test/api \
  test/repositories \
  test/schemas \
  test/delivery \
  test/ingestion_graph \
  test/recommendation_graph \
  -q
```

Tests under `test/mvp1` and `test/mvp2` may make real network requests and are excluded from the default command.

## Documentation

- [Project notes (Korean)](docs/Project.md)
- [Current handoff (Korean)](docs/HANDOFF.md)
