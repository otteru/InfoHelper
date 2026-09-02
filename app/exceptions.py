class SourceAlreadyExistsError(Exception):
    """이미 등록된 Source URL이다."""


class SourceNotFoundError(Exception):
    """source_id에 해당하는 Source가 없다."""


class CrawlRuleGenerationError(Exception):
    """HTML fetch 또는 CSS 스키마 생성에 실패했다."""


class CrawlRuleValidationError(Exception):
    """생성된 CSS 크롤링 규칙의 실제 추출 검증에 실패했다."""
