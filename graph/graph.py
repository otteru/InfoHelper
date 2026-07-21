from typing import TypedDict
from langgraph.graph import START, END, StateGraph
from state import RuleGenerationState
from crawl4ai import JsonCssExtractionStrategy, LLMConfig

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



def create_rule_generation_graph():
    graph = StateGraph(RuleGenerationState)
    
    
