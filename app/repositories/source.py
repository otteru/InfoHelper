from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from postgrest.exceptions import APIError
from supabase import Client

from app.exceptions import SourceAlreadyExistsError
from app.schemas.source import SourceCreate, SourceResponse


# 이 타입이 되려면 최소한 어떤 메서드를 가져야 하는지 정의한다.
class SourceRepository(Protocol):
    def create(self, source: SourceCreate) -> SourceResponse:
        """사이트를 저장하고 생성 결과를 반환한다."""
        # ...는 Python의 Ellipsis 객체 - “여기서는 구현하지 않는다.”
        ...


@dataclass(frozen=True)
class SupabaseSourceRepository:
    """Supabase sources 테이블에 접근한다."""

    client: Client

    def create(self, source: SourceCreate) -> SourceResponse:
        """사이트를 저장하고 생성된 데이터를 반환한다."""
        try:
            response = (
                self.client.table("sources")
                .insert(source.model_dump(mode="json"))
                .execute()
            )
        except APIError as error:
            # 23505는 PostgreSQL의 unique_violation (유니크 제약 조건 위반)을 의미한다.
            if error.code == "23505":
                raise SourceAlreadyExistsError from error

            raise

        rows = response.data

        if not isinstance(rows, list) or len(rows) != 1:
            raise RuntimeError("사이트 저장 결과가 올바르지 않습니다.")

        row = rows[0]

        if not isinstance(row, Mapping):
            raise RuntimeError("사이트 저장 데이터가 올바르지 않습니다.")

        return SourceResponse.model_validate(row)
