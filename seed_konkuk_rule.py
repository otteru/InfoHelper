"""로컬 DB에 건국대 공지 CSS 규칙을 저장하고 활성화한다."""

from uuid import UUID

from dotenv import load_dotenv

load_dotenv(".env.local", override=True)

from app.repositories.crawl_rule import SupabaseSourceCrawlRuleRepository
from app.schemas.crawl_rule import (
    CrawlRuleDefinition,
    GeneratedBy,
    SourceCrawlRuleCreate,
)
from integrations.clients import create_supabase_client

SOURCE_ID = UUID("f25944ce-c864-497b-9c74-df5bdaff229d")
KONKUK_SCHEMA = {
    "name": "Notice Board Items",
    "baseSelector": "table.board-table tbody tr",
    "fields": [
        {
            "name": "title",
            "selector": "td.td-subject strong",
            "type": "text",
        },
        {
            "name": "url",
            "selector": "td.td-subject a",
            "type": "attribute",
            "attribute": "href",
        },
    ],
}


def main() -> None:
    """건국대 규칙을 candidate로 저장한 뒤 active로 전환한다."""
    repo = SupabaseSourceCrawlRuleRepository(client=create_supabase_client())
    candidate = repo.create_candidate(
        SourceCrawlRuleCreate(
            source_id=SOURCE_ID,
            rule_definition=CrawlRuleDefinition.model_validate(KONKUK_SCHEMA),
            generated_by=GeneratedBy.LLM,
        )
    )
    print(candidate.id, candidate.status, candidate.version)

    active = repo.activate(candidate.id)
    print(active.status, active.health_status)


if __name__ == "__main__":
    main()
