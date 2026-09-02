"""크롤링 규칙 생성 API의 오류 응답을 검증한다."""

from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_crawl_rule_repository,
    get_source_repository,
)
from app.exceptions import CrawlRuleValidationError
from app.main import app
from app.schemas.source import SourceResponse

SOURCE_ID = UUID("00000000-0000-0000-0000-000000000010")


def test_create_crawl_rule_returns_422_for_validation_failure() -> None:
    """생성된 CSS 규칙이 검증에 실패하면 422를 반환한다."""
    source_repository = Mock()
    source_repository.get_by_id.return_value = SourceResponse(
        id=SOURCE_ID,
        name="테스트 공지",
        url="https://example.com/notices",
        created_at="2026-08-26T00:00:00+09:00",
    )
    crawl_rule_repository = Mock()
    app.dependency_overrides[get_source_repository] = (
        lambda: source_repository
    )
    app.dependency_overrides[get_crawl_rule_repository] = (
        lambda: crawl_rule_repository
    )

    try:
        with patch(
            "app.api.endpoints.crawl_rules.generate_candidate",
            new=AsyncMock(
                side_effect=CrawlRuleValidationError(
                    "유효한 공지가 없습니다."
                )
            ),
        ):
            response = TestClient(app).post(
                f"/api/v1/sources/{SOURCE_ID}/crawl_rules"
            )
    finally:
        app.dependency_overrides.pop(get_source_repository, None)
        app.dependency_overrides.pop(get_crawl_rule_repository, None)

    assert response.status_code == 422
    assert response.json()["detail"] == "생성된 크롤링 규칙이 유효하지 않습니다."
