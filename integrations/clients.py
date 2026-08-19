import os

from google import genai
from supabase import Client, create_client


def create_gemini_client() -> genai.Client:
    """환경변수를 사용해 Gemini 클라이언트를 생성한다."""
    google_api_key = os.environ.get("GOOGLE_API_KEY")

    if not google_api_key:
        raise RuntimeError("GOOGLE_API_KEY가 설정되지 않았습니다.")

    return genai.Client(api_key=google_api_key)


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
