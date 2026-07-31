from collections.abc import Mapping, Sequence
from html import escape
from typing import TypeAlias


Recommendation: TypeAlias = Mapping[str, object]
MAX_DIGEST_ITEMS = 5


def _get_text(
    recommendation: Recommendation,
    field: str,
) -> str:
    """추천 결과에서 필수 문자열 필드를 가져온다."""
    value = recommendation.get(field)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"추천 결과의 {field}가 올바른 문자열이 아닙니다.")

    return value.strip()


def _get_score(recommendation: Recommendation) -> float:
    """추천 점수를 백분율로 표시할 수 있도록 검증한다."""
    value = recommendation.get("total_score")

    if not isinstance(value, (int, float)):
        raise ValueError("추천 결과의 total_score가 올바른 숫자가 아닙니다.")

    return float(value)


def _get_matched_queries(
    recommendation: Recommendation,
) -> tuple[str, ...]:
    """추천 결과에서 매칭된 검색어를 가져온다."""
    value = recommendation.get("matched_queries", ())

    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or any(not isinstance(query, str) for query in value)
    ):
        raise ValueError("추천 결과의 matched_queries 형식이 올바르지 않습니다.")

    return tuple(query.strip() for query in value if query.strip())


def _render_query_badges(matched_queries: tuple[str, ...]) -> str:
    """매칭된 관심사를 이메일용 배지로 변환한다."""
    if not matched_queries:
        return """
                      <span style="display: inline-block; padding: 5px 10px;
                                   border-radius: 999px; background-color: #f3f4f6;
                                   color: #6b7280; font-size: 12px; line-height: 1.3;">
                        관심사 없음
                      </span>"""

    return "".join(
        f"""
                      <span style="display: inline-block; margin: 0 6px 6px 0;
                                   padding: 5px 10px; border-radius: 999px;
                                   background-color: #eef2ff; color: #4338ca;
                                   font-size: 12px; line-height: 1.3;">
                        {escape(query)}
                      </span>"""
        for query in matched_queries
    )


def _render_html_item(
    recommendation: Recommendation,
    index: int,
) -> str:
    """추천 공지 한 건을 이메일용 HTML 카드로 변환한다."""
    title = escape(_get_text(recommendation, "title"))
    url = escape(_get_text(recommendation, "url"), quote=True)
    summary = escape(_get_text(recommendation, "best_chunk"))
    score = _get_score(recommendation)
    matched_queries = _get_matched_queries(recommendation)
    query_badges = _render_query_badges(matched_queries)

    return f"""
        <tr>
          <td class="content-padding" style="padding: 0 32px 16px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                   style="border: 1px solid #e5e7eb; border-radius: 14px;
                          border-collapse: separate; background-color: #ffffff;">
              <tr>
                <td style="padding: 20px 20px 0;">
                  <table role="presentation" width="100%" cellpadding="0"
                         cellspacing="0">
                    <tr>
                      <td align="left" valign="middle">
                        <span style="display: inline-block; padding: 5px 9px;
                                     border-radius: 6px; background-color: #111827;
                                     color: #ffffff; font-size: 11px;
                                     font-weight: 700; letter-spacing: .04em;">
                          PICK {index}
                        </span>
                      </td>
                      <td align="right" valign="middle"
                          style="color: #4f46e5; font-size: 13px;
                                 font-weight: 700;">
                        적합도 {score:.0%}
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
              <tr>
                <td style="padding: 14px 20px 20px;">
                  <h2 style="margin: 0 0 10px; color: #111827;
                             font-size: 19px; line-height: 1.45;
                             letter-spacing: -.01em;">
                    {title}
                  </h2>
                  <p style="margin: 0 0 16px; color: #4b5563;
                            font-size: 14px; line-height: 1.7;">
                    {summary}
                  </p>
                  <div style="margin: 0 0 12px;">
                    <p style="margin: 0 0 8px; color: #9ca3af;
                              font-size: 11px; font-weight: 700;
                              letter-spacing: .04em;">
                      MATCHED INTERESTS
                    </p>
                    {query_badges}
                  </div>
                  <a href="{url}"
                     style="display: block; padding: 11px 16px;
                            border-radius: 8px; background-color: #4f46e5;
                            color: #ffffff; font-size: 14px;
                            font-weight: 700; line-height: 1.4;
                            text-align: center; text-decoration: none;">
                    원문 공지 보기
                  </a>
                </td>
              </tr>
            </table>
          </td>
        </tr>"""


def render_html_digest(
    recommendations: tuple[Recommendation, ...],
) -> str:
    """상위 추천 공지를 HTML 이메일 본문으로 만든다."""
    selected = recommendations[:MAX_DIGEST_ITEMS]
    items = "".join(
        _render_html_item(recommendation, index)
        for index, recommendation in enumerate(selected, start=1)
    )

    empty_message = """
        <tr>
          <td class="content-padding" style="padding: 0 32px 24px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                   style="border: 1px solid #e5e7eb; border-radius: 14px;
                          background-color: #f9fafb;">
              <tr>
                <td align="center" style="padding: 36px 24px;">
                  <p style="margin: 0 0 8px; color: #111827; font-size: 16px;
                            font-weight: 700; line-height: 1.5;">
                    오늘은 추천할 새로운 공지가 없습니다.
                  </p>
                  <p style="margin: 0; color: #6b7280; font-size: 13px;
                            line-height: 1.6;">
                    관심사에 맞는 새 공지를 찾으면 다음 다이제스트에서 알려드릴게요.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>"""

    body = items if items else empty_message
    recommendation_count = len(selected)
    count_text = (
        f"새로운 맞춤 공지 {recommendation_count}개를 정리했어요."
        if selected
        else "오늘 확인할 맞춤 공지가 있는지 살펴봤어요."
    )

    return f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>오늘의 추천 공지</title>
    <style>
      @media screen and (max-width: 600px) {{
        .email-shell {{ width: 100% !important; }}
        .outer-padding {{ padding: 16px 8px !important; }}
        .header-padding {{ padding: 24px 20px 22px !important; }}
        .content-padding {{ padding-left: 20px !important;
                            padding-right: 20px !important; }}
      }}
    </style>
  </head>
  <body style="margin: 0; padding: 0; background-color: #f3f4f6;
               font-family: Arial, 'Apple SD Gothic Neo', sans-serif;
               -webkit-text-size-adjust: 100%;">
    <div style="display: none; max-height: 0; overflow: hidden;
                color: transparent; opacity: 0;">
      관심사와 가장 잘 맞는 오늘의 추천 공지를 확인해 보세요.
    </div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           bgcolor="#f3f4f6"
           style="width: 100%; background-color: #f3f4f6;">
      <tr>
        <td class="outer-padding" align="center" style="padding: 32px 12px;">
          <table class="email-shell" role="presentation" width="600"
                 cellpadding="0" cellspacing="0" bgcolor="#ffffff"
                 style="width: 100%; max-width: 600px; background-color: #ffffff;
                        border: 1px solid #e5e7eb; border-radius: 16px;
                        border-collapse: separate; overflow: hidden;">
            <tr>
              <td class="header-padding" style="padding: 28px 32px 26px;">
                <table role="presentation" width="100%" cellpadding="0"
                       cellspacing="0">
                  <tr>
                    <td style="color: #4f46e5; font-size: 14px;
                               font-weight: 800; letter-spacing: .08em;">
                      INFO HELPER
                    </td>
                    <td align="right" style="color: #9ca3af; font-size: 11px;
                                            font-weight: 700;
                                            letter-spacing: .04em;">
                      DAILY DIGEST
                    </td>
                  </tr>
                </table>
                <div style="height: 1px; margin: 20px 0 22px;
                            background-color: #e5e7eb;"></div>
                <h1 style="margin: 0 0 8px; color: #111827;
                           font-size: 26px; line-height: 1.35;
                           letter-spacing: -.02em;">
                  오늘의 추천 공지
                </h1>
                <p style="margin: 0; color: #6b7280;
                          font-size: 14px; line-height: 1.65;">
                  {count_text}<br>
                  중요한 내용만 빠르게 확인해 보세요.
                </p>
              </td>
            </tr>
            {body}
            <tr>
              <td class="content-padding" style="padding: 6px 32px 28px;">
                <div style="height: 1px; margin-bottom: 18px;
                            background-color: #e5e7eb;"></div>
                <p style="margin: 0 0 5px; color: #6b7280; font-size: 12px;
                          font-weight: 700; line-height: 1.5;">
                  Info Helper
                </p>
                <p style="margin: 0; color: #9ca3af;
                          font-size: 11px; line-height: 1.6;">
                  등록한 관심사를 바탕으로 자동 생성된 추천 메일입니다.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def render_text_digest(
    recommendations: tuple[Recommendation, ...],
) -> str:
    """상위 추천 공지를 일반 텍스트 이메일 본문으로 만든다."""
    selected = recommendations[:MAX_DIGEST_ITEMS]

    if not selected:
        return (
            "오늘의 추천 공지\n\n"
            "오늘은 추천할 새로운 공지가 없습니다.\n\n"
            "Info Helper"
        )

    items = tuple(
        "\n".join(
            (
                f"{index}. {_get_text(recommendation, 'title')}",
                f"적합도: {_get_score(recommendation):.0%}",
                f"요약: {_get_text(recommendation, 'best_chunk')}",
                "매칭 관심사: "
                + (
                    ", ".join(_get_matched_queries(recommendation))
                    or "없음"
                ),
                f"공지 링크: {_get_text(recommendation, 'url')}",
            )
        )
        for index, recommendation in enumerate(selected, start=1)
    )

    return (
        "오늘의 추천 공지\n"
        "관심사와 가장 잘 맞는 공지를 모아 보내드립니다.\n\n"
        + "\n\n".join(items)
        + "\n\nInfo Helper"
    )
