from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from supabase import Client

from app.repositories.crawl_rule import SupabaseSourceCrawlRuleRepository
from app.repositories.source import SupabaseSourceRepository
from integrations.clients import create_supabase_client


@lru_cache
def get_supabase_client() -> Client:
    """애플리케이션에서 공유할 Supabase 클라이언트를 반환한다."""
    return create_supabase_client()


def get_source_repository(
    client: Annotated[
        Client,
        Depends(get_supabase_client),
    ],
) -> SupabaseSourceRepository:
    """Supabase Source Repository를 생성한다."""
    return SupabaseSourceRepository(client=client)


def get_crawl_rule_repository(
    client: Annotated[
        Client,
        Depends(get_supabase_client),
    ],
) -> SupabaseSourceCrawlRuleRepository:
    """Supabase Source Crawl Rule Repository를 생성한다."""
    return SupabaseSourceCrawlRuleRepository(client=client)
