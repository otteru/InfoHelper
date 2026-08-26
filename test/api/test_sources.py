from collections.abc import Iterator
from datetime import datetime
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_source_repository
from app.exceptions import SourceAlreadyExistsError
from app.main import app
from app.repositories.source import SourceRepository
from app.schemas.source import SourceCreate, SourceResponse
from integrations.url_safety import UnsafeUrlError


# 테스트용
class FakeSourceRepository:
    def create(self, source: SourceCreate) -> SourceResponse:
        return SourceResponse(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            name=source.name,
            url=source.url,
            created_at=datetime.fromisoformat("2026-08-15T00:00:00+09:00"),
        )


class DuplicateSourceRepository:
    def create(self, source: SourceCreate) -> SourceResponse:
        raise SourceAlreadyExistsError


# @pytest.fixture는 테스트에서 반복해서 필요한 준비물을 미리 만들어두는 기능
# Iterator는 값을 하나씩 순서대로 꺼낼 수 있는 객체의 타입을 나타내는 것
# 기존의 get_source_repository -> SupabaseSourceRepository 반환
@pytest.fixture
def client() -> Iterator[TestClient]:
    # FastAPI의 DI(Dependency Injection) 과정에서 대신 사용할 함수를 등록
    app.dependency_overrides[get_source_repository] = (
        lambda: FakeSourceRepository()
    )

    try:
        with (
            patch("app.api.endpoints.sources.validate_public_url"),
            TestClient(app) as test_client,
        ):
            # yield는 client를 전달한 뒤 테스트가 끝날 때까지 잠시 멈춘다.
            yield test_client
    # 테스트가 끝나면 dependency_overrides 제거
    finally:
        app.dependency_overrides.pop(get_source_repository, None)


def test_create_source(client: TestClient) -> None:
    request_body = {
        "name": "건국대학교",
        "url": "https://www.konkuk.ac.kr/notice",
    }

    response = client.post(
        "/api/v1/sources",
        json=request_body,
    )

    assert response.status_code == 201

    response_body = response.json()

    assert response_body["name"] == request_body["name"]
    assert response_body["url"] == request_body["url"]
    assert response_body["id"] == "00000000-0000-0000-0000-000000000001"
    assert datetime.fromisoformat(response_body["created_at"]).tzinfo is not None


def test_create_source_rejects_invalid_url(client: TestClient) -> None:
    request_body = {
        "name": "건국대학교",
        "url": "잘못된 주소",
    }

    response = client.post(
        "/api/v1/sources",
        json=request_body,
    )

    assert response.status_code == 422


def test_create_source_returns_409_for_duplicate_url(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_source_repository] = (
        lambda: DuplicateSourceRepository()
    )

    response = client.post(
        "/api/v1/sources",
        json={
            "name": "건국대학교",
            "url": "https://www.konkuk.ac.kr/notice",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "이미 등록된 사이트 URL입니다."


def test_create_source_returns_422_without_saving_unsafe_url(
    client: TestClient,
) -> None:
    """안전하지 않은 URL은 Source Repository에 저장하지 않는다."""
    repository = Mock(spec=SourceRepository)
    app.dependency_overrides[get_source_repository] = lambda: repository

    with patch(
        "app.api.endpoints.sources.validate_public_url",
        side_effect=UnsafeUrlError("공개 IP가 아닙니다."),
    ):
        response = client.post(
            "/api/v1/sources",
            json={
                "name": "내부 서비스",
                "url": "https://127.0.0.1/admin",
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "공개 웹사이트 URL만 등록할 수 있습니다."
    repository.create.assert_not_called()
