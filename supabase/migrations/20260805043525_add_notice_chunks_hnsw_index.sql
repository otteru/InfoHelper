-- 코사인 거리(<=>) 기반 유사도 검색을 가속하는 HNSW 인덱스다.
-- PostgreSQL 실행 계획이 유리하다고 판단하면 match_notice_chunks RPC에서 자동 사용한다.
create index notice_chunks_embedding_hnsw_idx
on public.notice_chunks
using hnsw (embedding extensions.vector_cosine_ops);
