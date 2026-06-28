from google import genai
from google.genai import types
from supabase import create_client, Client

from dotenv import load_dotenv
import os
from typing import Any, cast

def embed_question(question: str, gemini_client: genai.Client) -> list[float] :
    
    
    response = gemini_client.models.embed_content(
        model="gemini-embedding-2",
        contents=question, 
        config=types.EmbedContentConfig(output_dimensionality=1536),
    )
    
    if not response.embeddings:
        raise ValueError("임베딩 결과가 비어 있습니다.")

    values = response.embeddings[0].values
    
    if not values:
        raise ValueError("임베딩 값을 가져오지 못했습니다.")
        
    return values
    
    
def search_chunks(embedding: list[float]) -> list[dict] :
    # supabase - vector DB
    supabase_url = f"https://{os.environ["supabase_project_id"]}.supabase.co"
    supabase_secret_key = os.environ["supabase_secret_key"]
    supabase_client = create_client(supabase_url, supabase_secret_key)
    
    response = supabase_client.rpc(
        "match_notice_chunks",
        {
            "query_embedding": embedding,
            "match_count": 5,
        }
    ).execute()
    
    return cast(list[dict[str, Any]], response.data)
    
def build_prompt(question: str, chunks: list[dict]) -> str:
    
    prompt = f"사용자가 {question}을 질문을 했고 그 결과를 RAG로 찾은 결과가 {chunks}이다. 사용자에게 질문에 대한 대답을 RAG 결과를 기반으로 하여라"
    return prompt

def ask_gemini(prompt: str, gemini_client: genai.Client) :
    stream = gemini_client.interactions.create(
        model="gemini-2.5-flash",
        input = prompt,
        stream=True,
    )
    
    for event in stream:
        print(event)
    
def main() -> None:
    load_dotenv()
    gemini_client = genai.Client(api_key=os.environ["gemini-api-key"])

    question = input("질문: ")

    print("[1/4] 질문 임베딩 생성 중...")
    embedding = embed_question(question, gemini_client)
    print(f"[1/4] 임베딩 완료: {len(embedding)}차원")

    print("[2/4] Supabase 유사 chunk 검색 중...")
    chunks = search_chunks(embedding)
    print(f"[2/4] 검색 완료: {len(chunks)}개")

    for index, chunk in enumerate(chunks, start=1):
        print(f"- {index}. {chunk.get('title')} / similarity={chunk.get('similarity')}")

    print("[3/4] 프롬프트 생성 중...")
    prompt = build_prompt(question, chunks)
    print(f"[3/4] 프롬프트 길이: {len(prompt)}자")

    print("[4/4] Gemini 답변 생성 중...")
    answer = ask_gemini(prompt, gemini_client)
    
if __name__ == "__main__":
    main()