import pytest

from delivery.templates import render_html_digest, render_text_digest


def _recommendation(index: int) -> dict[str, object]:
    return {
        "notice_id": f"notice-{index}",
        "title": f"AI 프로그램 {index}",
        "url": f"https://example.com/notices/{index}",
        "best_chunk": f"AI 프로그램 {index}의 모집 안내입니다.",
        "matched_queries": ("AI 프로그램", "개발자 성장"),
        "total_score": 0.9,
    }


def test_html_digest는_상위_5개_추천만_표시한다() -> None:
    recommendations = tuple(_recommendation(index) for index in range(1, 7))

    result = render_html_digest(recommendations)

    assert "AI 프로그램 1" in result
    assert "AI 프로그램 5" in result
    assert "AI 프로그램 6" not in result
    assert "적합도 90%" in result
    assert "https://example.com/notices/1" in result


def test_html_digest는_외부_문자열을_escape한다() -> None:
    recommendation = {
        **_recommendation(1),
        "title": "<script>alert('xss')</script>",
    }

    result = render_html_digest((recommendation,))

    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_text_digest는_추천_정보를_일반_텍스트로_표시한다() -> None:
    result = render_text_digest((_recommendation(1),))

    assert "1. AI 프로그램 1" in result
    assert "적합도: 90%" in result
    assert "매칭 관심사: AI 프로그램, 개발자 성장" in result
    assert "공지 링크: https://example.com/notices/1" in result


@pytest.mark.parametrize(
    ("renderer", "expected"),
    (
        (render_html_digest, "오늘은 추천할 새로운 공지가 없습니다."),
        (render_text_digest, "오늘은 추천할 새로운 공지가 없습니다."),
    ),
)
def test_digest는_추천이_없으면_안내_문구를_표시한다(
    renderer: object,
    expected: str,
) -> None:
    assert callable(renderer)
    assert expected in renderer(())
