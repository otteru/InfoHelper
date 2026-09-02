import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from ai_graphs.ingestion_graph import nodes
from ai_graphs.ingestion_graph.models import CrawlFailure, NoticeTarget, Source
from app.schemas.crawl_rule import CrawlRuleDefinition
from integrations.url_safety import UnsafeUrlError

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

DUMMY_DETAIL_RULE = CrawlRuleDefinition.model_validate(
    {
        "name": "공지 상세",
        "baseSelector": "article",
        "fields": [
            {
                "name": "title",
                "selector": "h1",
                "type": "text",
            },
            {
                "name": "content",
                "selector": ".content",
                "type": "text",
            },
        ],
    }
)


@pytest.fixture(autouse=True)
def allow_public_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    """크롤링 노드 테스트에서 외부 DNS 검증을 대체한다."""
    monkeypatch.setattr(nodes, "validate_public_url", lambda url: None)


def make_source(
    name: str,
    url: str,
    source_id: str,
    detail_rule: CrawlRuleDefinition | None = None,
) -> Source:
    """테스트용 Source를 만든다."""
    return Source(
        id=UUID(source_id),
        name=name,
        url=url,
        rule_definition=DUMMY_RULE,
        detail_rule_definition=detail_rule,
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


class RecordingCrawler:
    """전달받은 URL을 기록하고 성공 결과를 반환하는 크롤러 대역 객체."""

    def __init__(
        self,
        received_urls: list[str],
        *,
        reverse_results: bool = False,
    ) -> None:
        """테스트가 검증할 URL 기록 목록을 받는다."""
        self.received_urls = received_urls
        self.reverse_results = reverse_results

    async def __aenter__(self) -> "RecordingCrawler":
        """비동기 컨텍스트에 크롤러를 제공한다."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """비동기 컨텍스트를 종료한다."""
        return None

    async def arun_many(
        self,
        urls: list[str],
        config: object,
    ) -> list[object]:
        """요청 URL을 기록하고 URL별 성공 결과를 반환한다."""
        self.received_urls.extend(urls)
        results = [
            SimpleNamespace(success=True, url=url)
            for url in urls
        ]
        return list(reversed(results)) if self.reverse_results else results


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


def test_안전하지_않은_url은_브라우저_호출_전에_차단한다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """목록과 상세 URL 모두 SSRF 검증을 통과해야 크롤링한다."""
    def reject_private_url(url: str) -> None:
        """테스트용 사설 URL을 거부한다."""
        if url == "https://127.0.0.1/admin":
            raise UnsafeUrlError("공개 IP가 아닙니다.")

    monkeypatch.setattr(
        nodes,
        "validate_public_url",
        reject_private_url,
    )
    crawler = Mock()
    monkeypatch.setattr(nodes, "AsyncWebCrawler", crawler)

    results = asyncio.run(
        nodes._crawl_throgh_crawl4ai(["https://127.0.0.1/admin"])
    )

    assert results == [
        CrawlFailure(
            url="https://127.0.0.1/admin",
            message="안전하지 않은 URL: 공개 IP가 아닙니다.",
        )
    ]
    crawler.assert_not_called()


def test_안전하지_않은_url은_안전한_url과_함께_크롤링하지_않는다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """혼합 URL 입력에서도 unsafe URL을 Crawl4AI 요청에서 제외한다."""
    safe_url = "https://public.example.com/notices"
    unsafe_url = "https://127.0.0.1/admin"
    received_urls: list[str] = []

    def reject_private_url(url: str) -> None:
        """테스트용 사설 URL을 거부한다."""
        if url == unsafe_url:
            raise UnsafeUrlError("공개 IP가 아닙니다.")

    monkeypatch.setattr(nodes, "validate_public_url", reject_private_url)
    monkeypatch.setattr(
        nodes,
        "AsyncWebCrawler",
        lambda config: RecordingCrawler(received_urls),
    )

    results = asyncio.run(
        nodes._crawl_throgh_crawl4ai([safe_url, unsafe_url])
    )

    assert received_urls == [safe_url]
    assert getattr(results[0], "url") == safe_url
    assert results[1] == CrawlFailure(
        url=unsafe_url,
        message="안전하지 않은 URL: 공개 IP가 아닙니다.",
    )


def test_crawl4ai_역순_결과를_요청_url_순서로_복원한다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """동시 크롤링 결과 순서가 달라도 URL에 맞는 결과를 반환한다."""
    first_url = "https://first.example.com/notices"
    second_url = "https://second.example.com/notices"
    received_urls: list[str] = []

    monkeypatch.setattr(
        nodes,
        "AsyncWebCrawler",
        lambda config: RecordingCrawler(
            received_urls,
            reverse_results=True,
        ),
    )

    results = asyncio.run(
        nodes._crawl_throgh_crawl4ai([first_url, second_url])
    )

    assert received_urls == [first_url, second_url]
    assert [result.url for result in results] == [first_url, second_url]


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
            title="공지",
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


def test_목록의_중복_상세_url은_한번만_추출한다(monkeypatch) -> None:
    """고정 공지와 일반 공지의 같은 상세 URL을 중복 크롤링하지 않는다."""
    source = make_source(
        "테스트 출처",
        "https://example.com/notices",
        "00000000-0000-0000-0000-000000000001",
    )
    strategy = SimpleNamespace(
        extract=lambda url, html: [
            {"title": "고정 공지", "url": "/notices/1"},
            {"title": "일반 공지", "url": "https://example.com/notices/1"},
        ]
    )
    monkeypatch.setattr(
        nodes,
        "JsonCssExtractionStrategy",
        lambda schema: strategy,
    )

    targets = nodes._notice_targets_from_html(source, "<table></table>")

    assert targets == (
        NoticeTarget(
            source_id=source.id,
            url="https://example.com/notices/1",
            title="고정 공지",
        ),
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
        {
            source_id: SimpleNamespace(
                rule_definition=DUMMY_RULE,
                detail_rule_definition=DUMMY_DETAIL_RULE,
            )
        },
    )

    result = nodes.load_sources({}, make_runtime())

    assert result["sources"] == (
        Source(
            id=source_id,
            name="건국대학교",
            url="https://www.konkuk.ac.kr/notice",
            rule_definition=DUMMY_RULE,
            detail_rule_definition=DUMMY_DETAIL_RULE,
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


def test_상세_규칙으로_제목과_본문을_추출한다(monkeypatch) -> None:
    """상세 Rule이 있으면 전체 Markdown 대신 추출한 제목과 본문을 사용한다."""
    async def fake_crawl(urls: list[str]) -> list[object]:
        return [
            SimpleNamespace(
                success=True,
                cleaned_html="<article></article>",
                html="<html></html>",
            )
        ]

    strategy = SimpleNamespace(
        extract=lambda url, html: [
            {"title": "상세 공지 제목", "content": "실제 공지 본문"}
        ]
    )
    monkeypatch.setattr(nodes, "_crawl_throgh_crawl4ai", fake_crawl)
    monkeypatch.setattr(
        nodes,
        "JsonCssExtractionStrategy",
        lambda schema: strategy,
    )

    result = asyncio.run(
        nodes.crawl_notice_pages(
            {
                "notice_targets": (
                    NoticeTarget(
                        source_id=UUID(
                            "00000000-0000-0000-0000-000000000003"
                        ),
                        url="https://example.com/notice/1",
                        title="목록 공지 제목",
                        detail_rule_definition=DUMMY_DETAIL_RULE,
                    ),
                ),
            }
        )
    )

    notice = result["notices"][0]
    assert notice.title == "상세 공지 제목"
    assert notice.content == "실제 공지 본문"


def test_상세_제목이_비면_목록_제목을_사용한다(monkeypatch) -> None:
    """상세 Rule의 제목이 비어 있으면 목록에서 추출한 제목을 사용한다."""
    target = NoticeTarget(
        source_id=UUID("00000000-0000-0000-0000-000000000003"),
        url="https://example.com/notice/1",
        title="목록 공지 제목",
        detail_rule_definition=DUMMY_DETAIL_RULE,
    )
    result = SimpleNamespace(
        success=True,
        cleaned_html="<article></article>",
        html="<html></html>",
    )
    strategy = SimpleNamespace(
        extract=lambda url, html: [{"title": "", "content": "공지 본문"}]
    )
    monkeypatch.setattr(
        nodes,
        "JsonCssExtractionStrategy",
        lambda schema: strategy,
    )

    notice = nodes._create_notice(target, result)

    assert notice.title == "목록 공지 제목"


def test_상세_추출_실패_공지를_무효_목록에_기록한다(monkeypatch) -> None:
    """수집은 성공했지만 상세 추출이 실패하면 기존 청크 삭제 대상으로 기록한다."""
    target = NoticeTarget(
        source_id=UUID("00000000-0000-0000-0000-000000000003"),
        url="https://example.com/notice/invalid",
        title="목록 제목",
        detail_rule_definition=DUMMY_DETAIL_RULE,
    )

    async def fake_crawl(urls: list[str]) -> list[object]:
        return [
            SimpleNamespace(
                success=True,
                cleaned_html="<article></article>",
                html="<html></html>",
            )
        ]

    strategy = SimpleNamespace(
        extract=lambda url, html: [{"title": "목록 제목", "content": ""}]
    )
    monkeypatch.setattr(nodes, "_crawl_throgh_crawl4ai", fake_crawl)
    monkeypatch.setattr(
        nodes,
        "JsonCssExtractionStrategy",
        lambda schema: strategy,
    )

    result = asyncio.run(
        nodes.crawl_notice_pages({"notice_targets": (target,)})
    )

    assert result["notices"] == ()
    assert result["invalid_notice_ids"] == (target.url,)


def test_무효_공지의_기존_청크를_삭제한다() -> None:
    """상세 추출 실패 notice_id의 기존 벡터 청크를 검색 대상에서 제거한다."""
    query = Mock()
    query.delete.return_value = query
    query.eq.return_value = query
    query.execute.return_value = SimpleNamespace(data=[])
    supabase = Mock()
    supabase.table.return_value = query
    runtime = SimpleNamespace(
        context=SimpleNamespace(
            gemini_client=object(),
            supabase_client=supabase,
        )
    )
    invalid_url = "https://example.com/notice/invalid"

    result = nodes.upsert_to_vectorDB(
        {
            "notices": (),
            "invalid_notice_ids": (invalid_url, invalid_url),
        },
        runtime,
    )

    assert result == {"saved_count": 0}
    query.delete.assert_called_once_with()
    query.eq.assert_called_once_with("notice_id", invalid_url)
    query.execute.assert_called_once_with()
