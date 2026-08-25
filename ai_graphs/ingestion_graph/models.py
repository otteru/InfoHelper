from uuid import UUID
from dataclasses import dataclass
from datetime import date

from app.schemas.crawl_rule import CrawlRuleDefinition


# sources 테이블에서 읽어 온 크롤링 출처
@dataclass(frozen=True)
class Source:
    """공지 목록 페이지를 제공하는 크롤링 출처."""

    id: UUID
    name: str
    url: str
    rule_definition: CrawlRuleDefinition


@dataclass(frozen=True)
class CrawlFailure:
    """크롤링 결과를 만들지 못한 URL의 실패 정보.
    일부 성공이 아니라 arun_many 자체가 예외를 던질 때의 경우이다."""

    url: str
    message: str


# 목록 페이지에서 발견했지만 아직 상세 내용을 가져오지 않은 공지
@dataclass(frozen=True)
class NoticeTarget:
    """상세 페이지 크롤링 대상 공지."""

    source_id: UUID
    url: str


# 상세 페이지를 크롤링·정제한 뒤 임베딩과 저장에 사용하는 공지 데이터
@dataclass(frozen=True)
class Notice:
    """임베딩 가능한 형태로 정제된 공지."""

    source_id: UUID
    url: str  # 중복 저장을 판별하는 공지의 고유 식별자
    title: str
    content: str
    deadline: date | None  # 마감일이 없는 공지는 None
