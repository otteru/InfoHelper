from datetime import datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app


def test_create_source() -> None:
    request_body = {
        "name": "건국대학교",
        "url": "https://www.konkuk.ac.kr/notice",
    }

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/sources",
            json=request_body,
        )

    assert response.status_code == 201

    response_body = response.json()

    assert response_body["name"] == request_body["name"]
    assert response_body["url"] == request_body["url"]
    assert UUID(response_body["id"])
    assert datetime.fromisoformat(response_body["created_at"]).tzinfo is not None


def test_create_source_rejects_invalid_url() -> None:
    request_body = {
        "name": "건국대학교",
        "url": "잘못된 주소",
    }

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/sources",
            json=request_body,
        )

    assert response.status_code == 422
