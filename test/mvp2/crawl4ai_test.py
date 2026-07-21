import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig


PROJECT_ROOT = Path(__file__).resolve().parents[2]
USER_URL_PATH = PROJECT_ROOT / "userURL.json"


@dataclass(frozen=True)
class Source:
    name: str
    url: str


def load_sources(path: Path = USER_URL_PATH) -> tuple[Source, ...]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    return tuple(
        Source(name=item["name"], url=item["url"])
        for item in data["resource"]
    )


def test_user_url에_크롤링할_주소가_존재한다() -> None:
    sources = load_sources()

    assert sources
    assert all(source.name.strip() for source in sources)
    assert all(urlparse(source.url).scheme in {"http", "https"} for source in sources)
    assert all(urlparse(source.url).netloc for source in sources)

def save_markdown(markdown: str) -> Path :
    file_path = Path(__file__).resolve().parent / "test.md"
    file_path.write_text(markdown, encoding="utf-8")
    
    return file_path

async def assert_sources_are_crawlable(sources: tuple[Source, ...]) -> None:
    browser_config = BrowserConfig(headless=True, verbose=True)
    crawler_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        for source in sources:
            result = await crawler.arun(url=source.url, config=crawler_config)
            
            print(f"\n[{source.name}] {source.url}")
            print(result.markdown.raw_markdown[:1000])
            
            save_markdown(result.markdown.raw_markdown)

            assert result.success, (
                f"{source.name} 크롤링 실패: {result.error_message}"
            )
            assert result.html, f"{source.name}에서 HTML을 가져오지 못했습니다."
            assert result.markdown.raw_markdown.strip(), (
                f"{source.name}에서 Markdown을 생성하지 못했습니다."
            )


def test_user_url을_crawl4ai로_크롤링한다() -> None:
    asyncio.run(assert_sources_are_crawlable(load_sources()))
