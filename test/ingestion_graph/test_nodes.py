import asyncio
from types import SimpleNamespace
from uuid import UUID

from ai_graphs.ingestion_graph import nodes
from ai_graphs.ingestion_graph.models import CrawlFailure, NoticeTarget, Source
from app.schemas.crawl_rule import CrawlRuleDefinition

DUMMY_RULE = CrawlRuleDefinition.model_validate(
    {
        "name": "공지 목록",
        "baseSelector": "table tbody tr",
        "fields": [
            {
                "name": "title",
                "selector": "a",
                "type": "text",
            },
            {
                "name": "url",
                "selector": "a",
                "type": "attribute",
                "attribute": "href",
            },
        ],
    }
)


def make_source(name: str, url: str, source_id: str) -> Source:
    """테스트용 Source를 만든다."""
    return Source(
        id=UUID(source_id),
        name=name,
        url=url,
        rule_definition=DUMMY_RULE,
    )


class FailingCrawler:
    """브라우저 시작 단계에서 실패하는 Crawl4AI 대역 객체."""

    async def __aenter__(self) -> "FailingCrawler":
        raise RuntimeError("브라우저 시작 실패")

    async def __aexit__(self, *args: object) -> None:
        return None


def test_arun_many_전체_예외를_url별_실패로_변환한다(monkeypatch) -> None:
    """크롤러 전체 예외가 각 URL의 CrawlFailure로 변환되는지 검증한다."""
    monkeypatch.setattr(
        nodes,
        "AsyncWebCrawler",
        lambda config: FailingCrawler(),
    )

    results = asyncio.run(
        nodes._crawl_throgh_crawl4ai(
            ["https://example.com/one", "https://example.com/two"],
        )
    )

    assert all(isinstance(result, CrawlFailure) for result in results)
    assert [result.url for result in results] == [
        "https://example.com/one",
        "https://example.com/two",
    ]


def test_목록_크롤링_실패를_errors에_기록한다(monkeypatch) -> None:
    """실패한 목록 페이지를 건너뛰고 성공한 목록의 URL만 추출한다."""
    async def fake_crawl(urls: list[str]) -> list[object]:
        return [
            CrawlFailure(url=urls[0], message="TimeoutError: 시간 초과"),
            SimpleNamespace(
                success=True,
                html=(
                    "<table><tbody><tr><td>"
                    '<a href="https://example.com/artclView.do?id=1">공지</a>'
                    "</td></tr></tbody></table>"
                ),
                cleaned_html=None,
            ),
        ]

    monkeypatch.setattr(nodes, "_crawl_throgh_crawl4ai", fake_crawl)

    result = asyncio.run(
        nodes.crawl_source_page(
            {
                "sources": (
                    make_source(
                        "실패 출처",
                        "https://fail.example.com",
                        "00000000-0000-0000-0000-000000000001",
                    ),
                    make_source(
                        "성공 출처",
                        "https://success.example.com",
                        "00000000-0000-0000-0000-000000000002",
                    ),
                ),
            }
        )
    )

    assert "notice_targets" in result
    assert result["notice_targets"] == (
        NoticeTarget(
            source_id=UUID("00000000-0000-0000-0000-000000000002"),
            url="https://example.com/artclView.do?id=1",
        ),
    )
    assert "errors" in result
    assert result["errors"] == (
        "https://fail.example.com: TimeoutError: 시간 초과",
    )


def test_상세_크롤링_실패를_errors에_기록한다(monkeypatch) -> None:
    """실패한 상세 공지를 건너뛰고 성공한 공지만 Notice로 만든다."""
    async def fake_crawl(urls: list[str]) -> list[object]:
        return [
            CrawlFailure(url=urls[0], message="RuntimeError: 브라우저 오류"),
            SimpleNamespace(
                success=True,
                metadata={"title": "성공 공지"},
                markdown=SimpleNamespace(raw_markdown="공지 본문"),
            ),
        ]

    monkeypatch.setattr(nodes, "_crawl_throgh_crawl4ai", fake_crawl)

    result = asyncio.run(
        nodes.crawl_notice_pages(
            {
                "notice_targets": (
                    NoticeTarget(
                        source_id=UUID(
                            "00000000-0000-0000-0000-000000000003"
                        ),
                        url="https://fail.example.com/notice",
                    ),
                    NoticeTarget(
                        source_id=UUID(
                            "00000000-0000-0000-0000-000000000003"
                        ),
                        url="https://success.example.com/notice",
                    ),
                ),
            }
        )
    )

    assert "notices" in result
    assert len(result["notices"]) == 1
    assert result["notices"][0].title == "성공 공지"
    assert "errors" in result
    assert result["errors"] == (
        "https://fail.example.com/notice: RuntimeError: 브라우저 오류",
    )
