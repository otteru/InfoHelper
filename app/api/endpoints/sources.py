from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_source_repository
from app.exceptions import SourceAlreadyExistsError
from app.repositories.source import SourceRepository
from app.schemas.source import SourceCreate, SourceResponse
from integrations.url_safety import UnsafeUrlError, validate_public_url

router = APIRouter(
    prefix="/sources",
    tags=["sources"],
)


@router.post(
    "",
    response_model=SourceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_source(
    source: SourceCreate,
    repository: Annotated[
        SourceRepository,
        Depends(get_source_repository),
    ],
) -> SourceResponse:
    """등록할 사이트 정보를 검증한다."""
    try:
        validate_public_url(str(source.url))
        return repository.create(source)
    except UnsafeUrlError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="공개 웹사이트 URL만 등록할 수 있습니다.",
        ) from error
    except SourceAlreadyExistsError as error:
        # 원래 예외를 HTTP 예외의 원인으로 연결한다.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 등록된 사이트 URL입니다.",
        ) from error
