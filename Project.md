
# 프로젝트 개요

프로젝트 명 : InfoHelper

한 줄 설명 : 사용자가 공지 사이트 url을 등록과 사용자 정보를 등록을 해주면 주기적으로 사용자 정보에 알맞은 정보를 찾아서 선제적으로 제안을 해준다.

프로젝트 목표 : RAG, DeepAgents(Langchain), AWS등의 기술 스택 공부 및 실제 배포 운영 경험

프로젝트 진행 기조 : 애자일, 잦은 출시, 배포

## 스택

workflow : Langchain, Langgraph
DB : Supabase + pgvector

```sql
rows.append({
    "notice_id": notice_id,   # 같은 공지에서 나온 chunk들을 묶는 ID
    "title": title,           # 공지 제목
    "url": url,               # 원문 공지 링크
    "content": chunk,         # 실제 임베딩할 텍스트 조각
    "deadline": deadline,     # 신청/지원 마감일
    "source_id": source_id,   # 공지를 가져온 출처 ID
    "status": "open",        # 공지 상태: open / expired / hidden 등
    "embedding": embedding    # content를 임베딩한 벡터
})
```

## 목표

### 1차 완성물

- supabase에 vector db 구축
- RAG를 통해서 내가 질문한 것을 찾아오게 하기

## 2차 완성물

- LangChain, LangGraph으로 update
- Crawling을 Crawl4Ai 도입
  - 처음에는 AI를 통해 CSS/XPath schema를 만들게 하고 그걸 기반으로 Crawl4AI를 통해서 CSS/XPath schema로 뽑게 하기.

- langgraph nodes 흐름 :
  1) main.py에 url이 들어옴
  2) fetch 날려서 목록들 있는 html 들고오기
  3) LLM으로 해당 html 기반 CSS/XPath 스키마 제작
  4) crawl4ai로 테스트 및 안될 때 피드백 루프 제작 (max:3)
  5) 목록들 중 1개만 가져와서 상세 글 html 들고오기
  6) LLM으로 해당 html 기반 CSS/XPath 스키마 제작
  7) crawl4ai로 테스트 및 안될 때 피드백 루프 제작 (max:3)