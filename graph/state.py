from typing import TypedDict

class RuleGenerationState(TypedDict):
    start_url: str
    list_html: str
    list_schema: dict | None
    list_errors: list[str]
    detail_urls: list[str]
    detail_html_samples: list[str]
    detail_schema: dict | None
    detail_errors: list[str]
    list_retry_count: int
    detail_retry_count: int