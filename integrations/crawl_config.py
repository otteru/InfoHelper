"""사이트별 Crawl4AI 실행 설정을 생성한다."""

from crawl4ai import CacheMode, CrawlerRunConfig

from app.schemas.crawl_rule import CrawlMode


def create_crawler_run_config(mode: CrawlMode) -> CrawlerRunConfig:
    """수집 모드에 맞는 Crawl4AI 실행 설정을 만든다."""
    common = {
        "cache_mode": CacheMode.BYPASS,
        "stream": False,
    }
    if mode is CrawlMode.DEFAULT:
        return CrawlerRunConfig(**common)
    if mode is CrawlMode.DYNAMIC:
        return CrawlerRunConfig(
            **common,
            wait_until="networkidle",
            delay_before_return_html=5,
        )
    return CrawlerRunConfig(
        **common,
        wait_until="networkidle",
        delay_before_return_html=5,
        scan_full_page=True,
        max_scroll_steps=2,
        scroll_delay=1,
    )
