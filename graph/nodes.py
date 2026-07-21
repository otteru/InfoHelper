from state import RuleGenerationState
from tools import fetch_html, setup_gemini_model
from dotenv import load_dotenv

from typing import TypedDict



#================================================================
# workflow
# 1. main.py에 start_url 입력
# 2. Crawl4AI로 목록 페이지 html fetch
# 3. LLM으로 list CSS/XPath schema 생성
# 4. Crawl4AI로 list_schema 테스트
# 5. 실패하면 피드백 루프 max 3
# 6. 추출된 상세 URL들을 절대 URL로 변환
# 7. 상세 URL 1~3개 선택
# 8. Crawl4AI로 상세 글 html fetch
# 9. LLM으로 detail CSS/XPath schema 생성
# 10. Crawl4AI로 detail_schema 테스트
# 11. 실패하면 피드백 루프 max 3
# 12. list_schema + detail_schema를 하나의 rule 파일로 저장
# 13. index.json에 start_url prefix 등록
#================================================================

load_dotenv()

def fetch_list_html(state: RuleGenerationState) -> RuleGenerationState :
    html = fetch_html(state['start_url'])
    
    gemini_client = setup_gemini_model("gemini-2.5-flash")
    
    
    return state