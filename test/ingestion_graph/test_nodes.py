import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest

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


def make_runtime() -> SimpleNamespace:
    """load_sources에 넘길 가짜 Graph runtime을 만든다."""
    return SimpleNamespace(context=SimpleNamespace(supabase_client=object()))


def patch_source_repos(
    monkeypatch: pytest.MonkeyPatch,
    source_rows: tuple[object, ...],
    rules_by_id: dict[UUID, object],
) -> None:
    """load_sources가 사용할 가짜 Repository를 주입한다."""
    monkeypatch.setattr(
        nodes,
        "SupabaseSourceRepository",
        lambda client: SimpleNamespace(list_all=lambda: source_rows),
    )
    monkeypatch.setattr(
        nodes,
        "SupabaseSourceCrawlRuleRepository",
        lambda client: SimpleNamespace(
            get_active=lambda source_id: rules_by_id.get(source_id)
        ),
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


def test_css_추출_예외를_errors에_기록한다(monkeypatch) -> None:
    """CSS 추출 예외는 해당 Source만 실패로 기록하고 다른 Source는 계속 처리한다."""
    fail_source = make_source(
        "실패 출처",
        "https://fail.example.com",
        "00000000-0000-0000-0000-000000000001",
    )
    success_source = make_source(
        "성공 출처",
        "https://success.example.com",
        "00000000-0000-0000-0000-000000000002",
    )
    success_target = NoticeTarget(
        source_id=success_source.id,
        url="https://success.example.com/artclView.do?id=1",
    )

    async def fake_crawl(urls: list[str]) -> list[object]:
        return [
            SimpleNamespace(
                success=True,
                html="<html></html>",
                cleaned_html=None,
            )
            for _ in urls
        ]

    def fake_extract(source: Source, html: str) -> tuple[NoticeTarget, ...]:
        if source.id == fail_source.id:
            raise RuntimeError("잘못된 CSS 스키마")
        return (success_target,)

    monkeypatch.setattr(nodes, "_crawl_throgh_crawl4ai", fake_crawl)
    monkeypatch.setattr(nodes, "_notice_targets_from_html", fake_extract)

    result = asyncio.run(
        nodes.crawl_source_page(
            {"sources": (fail_source, success_source)},
        )
    )

    assert result["notice_targets"] == (success_target,)
    assert result["errors"] == (
        "https://fail.example.com: RuntimeError: 잘못된 CSS 스키마",
    )


def test_load_sources_source와_active_규칙을_결합한다(monkeypatch) -> None:
    """active 규칙이 있는 Source를 배치 Source로 만든다."""
    source_id = UUID("00000000-0000-0000-0000-000000000001")
    source_row = SimpleNamespace(
        id=source_id,
        name="건국대학교",
        url="https://www.konkuk.ac.kr/notice",
    )
    patch_source_repos(
        monkeypatch,
        (source_row,),
        {source_id: SimpleNamespace(rule_definition=DUMMY_RULE)},
    )

    result = nodes.load_sources({}, make_runtime())

    assert result["sources"] == (
        Source(
            id=source_id,
            name="건국대학교",
            url="https://www.konkuk.ac.kr/notice",
            rule_definition=DUMMY_RULE,
        ),
    )


def test_load_sources_active_규칙_없는_source를_제외한다(monkeypatch) -> None:
    """active 규칙이 없는 Source는 배치 목록에서 뺀다."""
    with_rule_id = UUID("00000000-0000-0000-0000-000000000001")
    without_rule_id = UUID("00000000-0000-0000-0000-000000000002")
    patch_source_repos(
        monkeypatch,
        (
            SimpleNamespace(
                id=with_rule_id,
                name="규칙 있음",
                url="https://with.example.com",
            ),
            SimpleNamespace(
                id=without_rule_id,
                name="규칙 없음",
                url="https://without.example.com",
            ),
        ),
        {with_rule_id: SimpleNamespace(rule_definition=DUMMY_RULE)},
    )

    result = nodes.load_sources({}, make_runtime())

    assert result["sources"] == (
        Source(
            id=with_rule_id,
            name="규칙 있음",
            url="https://with.example.com",
            rule_definition=DUMMY_RULE,
        ),
    )


def test_load_sources_빈_목록을_처리한다(monkeypatch) -> None:
    """등록된 Source가 없으면 빈 튜플을 반환한다."""
    patch_source_repos(monkeypatch, (), {})

    result = nodes.load_sources({}, make_runtime())

    assert result["sources"] == ()


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
