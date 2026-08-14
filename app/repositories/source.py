from collections.abc import Mapping
from dataclasses import dataclass

from supabase import Client

from app.schemas.source import SourceCreate, SourceResponse


@dataclass(frozen=True)
class SupabaseSourceRepository:
    """Supabase sources 테이블에 접근한다."""

    client: Client

    def create(self, source: SourceCreate) -> SourceResponse:
        """사이트를 저장하고 생성된 데이터를 반환한다."""
        response = (
            self.client.table("sources")
            .insert(source.model_dump(mode="json"))
            .execute()
        )

        rows = response.data

        if not isinstance(rows, list) or len(rows) != 1:
            raise RuntimeError("사이트 저장 결과가 올바르지 않습니다.")

        row = rows[0]

        if not isinstance(row, Mapping):
            raise RuntimeError("사이트 저장 데이터가 올바르지 않습니다.")

        return SourceResponse.model_validate(row)