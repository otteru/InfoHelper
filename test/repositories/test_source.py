"""SupabaseSourceRepository의 저장 동작을 실제 DB 없이 검증한다."""

from datetime import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock
from uuid import UUID

import pytest
from postgrest.exceptions import APIError
from pydantic import HttpUrl
from supabase import Client

from app.exceptions import SourceAlreadyExistsError
from app.repositories.source import SupabaseSourceRepository
from app.schemas.source import SourceCreate


def create_repository(
    response_data: object,
) -> tuple[SupabaseSourceRepository, Mock, Mock]:
    """Supabase 응답을 원하는 값으로 설정한 Repository와 Mock을 만든다."""
    # spec을 지정하면 실제 Client에 없는 속성을 잘못 사용할 때 테스트가 실패한다.
    client = Mock(spec=Client)

    # query는 client.table().insert().execute() 호출을 대신할 가짜 객체다.
    query = Mock()

    # client.table("sources")가 query를 반환하도록 설정한다.
    client.table.return_value = query

    # insert() / select() 뒤에도 같은 query를 반환해 메서드 체인을 이어간다.
    query.insert.return_value = query
    query.select.return_value = query

    # SimpleNamespace는 원하는 속성을 간단하게 가진 객체를 만드는 도구
    query.execute.return_value = SimpleNamespace(data=response_data)

    # 실행 시점에는 Mock이 Client 역할을 하지만, 정적 타입 검사기에는
    # Client로 취급하라고 cast로 알려준다. 실제 객체를 변환하지는 않는다.
    repository = SupabaseSourceRepository(
        client=cast(Client, client),
    )

    # 결과 검증에는 repository를, 호출 검증에는 client와 query를 사용한다.
    return repository, client, query


# 정상 저장 흐름을 검사
def test_create_returns_saved_source() -> None:
    """정상 Supabase 응답을 SourceResponse로 변환하는지 검증한다."""
    # Arrange: Repository에 전달할 사이트 등록 요청을 준비한다.
    source = SourceCreate(
        name="건국대학교",
        url=HttpUrl("https://www.konkuk.ac.kr/notice"),
    )

    # 실제 Supabase가 INSERT 후 반환한다고 가정한 행 데이터다.
    response_data = [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "name": "건국대학교",
            "url": "https://www.konkuk.ac.kr/notice",
            "created_at": "2026-08-15T00:00:00+09:00",
        }
    ]

    # 위 응답을 반환하도록 Mock Client가 담긴 Repository를 준비한다.
    repository, client, query = create_repository(response_data)

    # Act: 테스트 대상인 실제 Repository의 create()를 실행한다.
    result = repository.create(source)

    # Assert: Supabase 응답이 올바른 타입과 값으로 변환됐는지 확인한다.
    assert result.id == UUID(
        "00000000-0000-0000-0000-000000000001"
    )
    assert result.name == source.name
    assert result.url == source.url
    assert result.created_at == datetime.fromisoformat(
        "2026-08-15T00:00:00+09:00"
    )

    # Repository가 정확한 테이블을 선택했는지 확인한다.
    client.table.assert_called_once_with("sources")

    # 요청 모델이 JSON 저장 가능한 데이터로 변환되어 전달됐는지 확인한다.
    query.insert.assert_called_once_with(
        source.model_dump(mode="json")
    )

    # INSERT 쿼리가 정확히 한 번 실행됐는지 확인한다.
    query.execute.assert_called_once_with()


@pytest.mark.parametrize(
    "response_data",
    [
        # 각 항목은 같은 테스트를 독립적으로 한 번씩 실행한다.
        pytest.param(None, id="none"),
        pytest.param({}, id="mapping"),
        pytest.param([], id="empty-list"),
        pytest.param([{}, {}], id="multiple-rows"),
    ],
)
def test_create_rejects_invalid_response_data(
    response_data: object,
) -> None:
    """응답이 단 하나의 행을 가진 리스트가 아니면 거부하는지 검증한다."""
    # Arrange: 유효한 요청과 비정상 Supabase 응답을 준비한다.
    source = SourceCreate(
        name="건국대학교",
        url=HttpUrl("https://www.konkuk.ac.kr/notice"),
    )
    repository, _, _ = create_repository(response_data)

    # Act & Assert: create()가 지정한 RuntimeError를 발생시켜야 한다.
    with pytest.raises(
        RuntimeError,
        match="사이트 저장 결과가 올바르지 않습니다",
    ):
        repository.create(source)


def test_create_rejects_invalid_row() -> None:
    """응답 리스트 안의 행이 객체 형식이 아니면 거부하는지 검증한다."""
    # Arrange: 요청은 정상이지만 응답의 첫 행은 문자열로 준비한다.
    source = SourceCreate(
        name="건국대학교",
        url=HttpUrl("https://www.konkuk.ac.kr/notice"),
    )
    repository, _, _ = create_repository(["잘못된 데이터"])

    # Act & Assert: 행 형식 오류에 해당하는 RuntimeError를 확인한다.
    with pytest.raises(
        RuntimeError,
        match="사이트 저장 데이터가 올바르지 않습니다",
    ):
        repository.create(source)


# 중복 URL 오류
def test_create_translates_duplicate_url_error() -> None:
    """중복 URL 오류를 SourceAlreadyExistsError로 변환하는지 검증한다."""

    source = SourceCreate(
        name="건국대학교",
        url=HttpUrl("https://www.konkuk.ac.kr/notice"),
    )

    repository, _, query = create_repository(None)

    query.execute.side_effect = APIError(
        {
            "code": "23505",
            "message": "duplicate key value",
            "details": "Key (url) already exists.",
            "hint": None,
        }
    )

    with pytest.raises(SourceAlreadyExistsError):
        repository.create(source)


def test_list_all_returns_sources() -> None:
    """사이트 목록 응답을 SourceResponse 튜플로 변환하는지 검증한다."""
    response_data = [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "name": "건국대학교",
            "url": "https://www.konkuk.ac.kr/notice",
            "created_at": "2026-08-15T00:00:00+09:00",
        },
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "name": "다른 대학",
            "url": "https://example.com/notice",
            "created_at": "2026-08-16T00:00:00+09:00",
        },
    ]
    repository, client, query = create_repository(response_data)

    result = repository.list_all()

    assert len(result) == 2
    assert result[0].id == UUID("00000000-0000-0000-0000-000000000001")
    assert result[0].name == "건국대학교"
    assert result[1].id == UUID("00000000-0000-0000-0000-000000000002")
    client.table.assert_called_once_with("sources")
    query.select.assert_called_once_with("*")
    query.insert.assert_not_called()


def test_list_all_returns_empty_tuple() -> None:
    """사이트가 없으면 빈 튜플을 반환한다."""
    repository, _, query = create_repository([])

    result = repository.list_all()

    assert result == ()
    query.select.assert_called_once_with("*")


@pytest.mark.parametrize(
    "response_data",
    [
        pytest.param(None, id="none"),
        pytest.param({}, id="mapping"),
    ],
)
def test_list_all_rejects_invalid_response_data(
    response_data: object,
) -> None:
    """목록 응답이 리스트가 아니면 거부한다."""
    repository, _, _ = create_repository(response_data)

    with pytest.raises(
        RuntimeError,
        match="사이트 목록 결과가 올바르지 않습니다",
    ):
        repository.list_all()
