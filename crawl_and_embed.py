from dotenv import load_dotenv
import os
import json
from dataclasses import dataclass
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from google import genai
from google.genai import types
from supabase import create_client, Client

# =====================================
# 1차 mvp : 건국대학교 공지글에 대해서만 임베딩
# =====================================

# frozen=True -> 읽기 전용, 수정 불가
@dataclass(frozen=True)
class Source:
    name : str
    url : str
    
@dataclass(frozen=True)
class Notice:
    title : str
    url : str
    content : str
    source_id : str


def load_sources(path: str = "userURL.json") -> list[Source] :
    with open(path, "r", encoding="UTF-8") as file:
        data = json.load(file)
        
    return [Source(name=item["name"], url=item["url"]) for item in data["resource"]]

def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            # 예전 Netscape/Mozilla 계열 브라우저처럼 보이기 위한 관습적 접두어
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " 
            #Chrome과 Safari가 공통으로 영향을 받은 렌더링 엔진 계열 이름
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.konkuk.ac.kr/",
    }
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.text

def parse_notice_links(source: Source, list_html: str) -> list[str]:
    # BeautifulSoup 객체 생성
    soup = BeautifulSoup(list_html, "html.parser")
    
    links = [
        urljoin(source.url, str(anchor["href"]))
        for anchor in soup.select("a[href*='artclView.do']")
    ]
    
    return links
    

def parse_notice_page(source: Source, url: str) -> Notice:
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text(strip=True) if soup.title else "제목 없음"
    content = soup.get_text("\n", strip=True)
    
    return Notice(
        title=title,
        url=url,
        content=content,
        source_id=source.name,
    )

def split_text(text:str, chunk_size: int = 1000) -> list[str] :
    
    return [
        text[index:index + chunk_size]
        for index in range(0, len(text), chunk_size) 
        if text[index:index + chunk_size].strip()
    ]
    
def create_embedding(client: genai.Client, title: str, text: str) -> list[float]:
    content = f"title: {title} | text: {text}"

    response = client.models.embed_content(
        model="gemini-embedding-2",
        contents=content,
        config=types.EmbedContentConfig(output_dimensionality=1536),
    )

    if not response.embeddings:
        raise ValueError("임베딩 결과가 비어 있습니다.")

    values = response.embeddings[0].values
    if not values:
        raise ValueError("임베딩 값을 가져오지 못했습니다.")
        
    return values

def save_chunk(
    supabase: Client ,
    notice: Notice,
    chunk: str,
    embedding: list[float],
) -> None:
    
    supabase.table
    supabase.table("notice_chunks").insert({
        "notice_id": notice.url,
        "title": notice.title,
        "url": notice.url,
        "content": chunk,
        "deadline": None,
        "source_id": notice.source_id,
        "status": "open",
        "embedding": embedding,
    }).execute()
    
def main() -> None:
    load_dotenv()
    
    # embedding model     
    gemini_client = genai.Client(api_key = os.environ["GOOGLE_API_KEY"])
    
    
    # supabase - vector DB
    supabase_url = f"https://{os.environ["supabase_project_id"]}.supabase.co"
    supabase_secret_key = os.environ["supabase_secret_key"]
    supabase_client = create_client(supabase_url, supabase_secret_key)
    
    
    for source in load_sources() :
        list_html = fetch_html(source.url)
        # 공지 페이지의 공지 글들 링크 리스트 정리
        notice_urls = parse_notice_links(source, list_html)
        
        for url in notice_urls :
            #공지글 페이지 파싱
            notice = parse_notice_page(source, url)
            
            for chunk in split_text(notice.content) : 
                embedding = create_embedding(gemini_client, notice.title, chunk)
                save_chunk(supabase_client, notice, chunk, embedding)
            
        
        
if __name__ == "__main__" :
    main()
