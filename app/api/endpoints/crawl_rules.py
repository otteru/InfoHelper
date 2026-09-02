from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_crawl_rule_repository,
    get_source_repository,
)
from app.exceptions import (
    CrawlRuleGenerationError,
    CrawlRuleValidationError,
    SourceNotFoundError,
)
from app.repositories.crawl_rule import SourceCrawlRuleRepository
from app.repositories.source import SourceRepository
from app.schemas.crawl_rule import SourceCrawlRuleResponse
from app.services.crawl_rule import generate_candidate

router = APIRouter(
    prefix="/sources/{source_id}/crawl_rules",
    tags=["crawl-rules"],
)


@router.post(
    "",
    response_model=SourceCrawlRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_crawl_rule(
    source_id: UUID,
    source_repository: Annotated[
        SourceRepository,
        Depends(get_source_repository),
    ],
    crawl_rule_repository: Annotated[
        SourceCrawlRuleRepository,
        Depends(get_crawl_rule_repository),
    ],
) -> SourceCrawlRuleResponse:
    """사이트에 대한 새로운 크롤링 규칙을 생성한다."""
    try:
        source = source_repository.get_by_id(source_id)
        if source is None:
            raise SourceNotFoundError
        return await generate_candidate(source, crawl_rule_repository)
    except SourceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="등록되지 않은 사이트입니다.",
        ) from error
    except CrawlRuleValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="생성된 크롤링 규칙이 유효하지 않습니다.",
        ) from error
    except CrawlRuleGenerationError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="크롤링 규칙을 생성하지 못했습니다.",
        ) from error
