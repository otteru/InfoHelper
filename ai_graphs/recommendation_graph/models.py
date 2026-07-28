from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievedChunk:
    """추천 query로 검색된 공지 청크."""

    notice_id: str
    title: str
    url: str
    content: str
    similarity: float
    matched_query: str
