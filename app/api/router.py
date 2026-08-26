from fastapi import APIRouter

from app.api.endpoints.crawl_rules import router as crawl_rules_router
from app.api.endpoints.sources import router as sources_router

api_router = APIRouter()


@api_router.get("/health")
def health_check() -> dict[str, str]:
    """API 서버 상태를 확인한다."""
    return {"status": "ok"}

api_router.include_router(sources_router)
api_router.include_router(crawl_rules_router)
