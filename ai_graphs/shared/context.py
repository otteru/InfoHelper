from dataclasses import dataclass

from openai import OpenAI
from supabase import Client


@dataclass(frozen=True)
class GraphContext:
    """AI Graph 실행에 공통으로 필요한 외부 서비스 의존성."""

    embedding_client: OpenAI
    supabase_client: Client
