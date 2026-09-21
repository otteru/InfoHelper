import os
import math

from openai import OpenAI
from supabase import Client, create_client

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
GENERATION_MODEL = "google/gemini-3.6-flash"
EMBEDDING_MODEL = "qwen/qwen3-embedding-8b"
EMBEDDING_DIMENSIONS = 1536
CRAWL4AI_GENERATION_PROVIDER = f"openrouter/{GENERATION_MODEL}"


def create_openrouter_client() -> OpenAI:
    """환경변수를 사용해 OpenRouter 클라이언트를 생성한다."""
    api_key = os.environ.get("OPENROUTER_API_KEY")

    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY가 설정되지 않았습니다.")

    return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)


def create_embedding(
    client: OpenAI,
    text: str,
    *,
    model: str = EMBEDDING_MODEL,
    dimensions: int = EMBEDDING_DIMENSIONS,
) -> list[float]:
    """텍스트를 OpenRouter 임베딩 벡터로 변환한다."""
    values, _ = create_embedding_with_cost(client, text, model=model, dimensions=dimensions)
    return values


def create_embedding_with_cost(
    client: OpenAI,
    text: str,
    *,
    model: str = EMBEDDING_MODEL,
    dimensions: int = EMBEDDING_DIMENSIONS,
) -> tuple[list[float], float | None]:
    """임베딩 벡터와 응답에 명시된 OpenRouter API 비용을 반환한다."""
    response = client.embeddings.create(
        model=model,
        input=text,
        dimensions=dimensions,
    )

    if not response.data:
        raise ValueError("임베딩 결과가 비어 있습니다.")

    values = response.data[0].embedding
    if not values:
        raise ValueError("임베딩 값을 가져오지 못했습니다.")

    usage = getattr(response, 'usage', None)
    cost = getattr(usage, 'cost', None)
    if cost is not None and (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0):
        raise ValueError('임베딩 API 비용은 유한한 0 이상의 숫자여야 합니다')
    return values, float(cost) if cost is not None else None


def create_supabase_client() -> Client:
    """환경변수를 사용해 Supabase 클라이언트를 생성한다."""
    supabase_url = os.environ.get("SUPABASE_URL")
    project_id = os.environ.get("SUPABASE_PROJECT_ID")
    supabase_secret_key = os.environ.get("SUPABASE_SECRET_KEY")

    if not supabase_url and project_id:
        supabase_url = f"https://{project_id}.supabase.co"

    if not supabase_url or not supabase_secret_key:
        raise RuntimeError("Supabase 환경 변수가 설정되지 않았습니다.")

    return create_client(supabase_url, supabase_secret_key)
