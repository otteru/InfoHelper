from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, status

from app.schemas.source import SourceCreate, SourceResponse

router = APIRouter(
    prefix="/sources",
    tags=["sources"],
)


@router.post(
    "",
    response_model=SourceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_source(source: SourceCreate) -> SourceResponse:
    """등록할 사이트 정보를 검증한다."""
    return SourceResponse(
        id=uuid4(),
        name=source.name,
        url=source.url,
        created_at=datetime.now(UTC),
    )
