FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    CRAWL4_AI_BASE_DIRECTORY=/app

WORKDIR /app

COPY pyproject.toml main.py ./
COPY ai_graphs ./ai_graphs
COPY delivery ./delivery

RUN pip install .
RUN crawl4ai-setup

COPY crawl_rules ./crawl_rules
COPY data ./data

CMD ["python", "main.py"]
