from dataclasses import dataclass

from google import genai
from supabase import Client


@dataclass(frozen=True)
class IngestionContext:
    """Ingestion Graph 실행에 필요한 외부 서비스 의존성."""

    gemini_client: genai.Client
    supabase_client: Client
