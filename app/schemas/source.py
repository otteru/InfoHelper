from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class SourceCreate(BaseModel):
    """사이트 등록 요청 데이터."""

    name: Annotated[str, Field(min_length=1, max_length=100)]
    url: HttpUrl


class SourceResponse(SourceCreate):
    """사이트 등록 응답 데이터."""

    id: UUID
    created_at: datetime
