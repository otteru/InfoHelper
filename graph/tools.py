import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types
import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.language_models.chat_models import BaseChatModel

load_dotenv()

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

def setup_gemini_model(model_name: str) -> BaseChatModel  :
    model = ChatGoogleGenerativeAI(
        model= model_name,
        temperature=0.8,
    )
    
    return model