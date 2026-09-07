"""직행 수집기의 원문 정합성·중복 제거·중단 복구를 검증한다."""

from pathlib import Path
from typing import Any
from unittest.mock import Mock
from uuid import UUID

import pytest
import requests

from RAG_evaluation.crawler import zighang as crawler


def job_id(number: int) -> str:
    """테스트 번호에 대응하는 고정 UUID를 만든다."""
    return str(UUID(int=number))


def listing(number: int) -> dict[str, Any]:
    """IT 필터에 속하는 테스트 목록 항목을 만든다."""
    return {"id": job_id(number), "depthTwos": ["서버_백엔드"]}


def detail(number: int, text: str = "Python 개발자를 채용합니다.") -> dict[str, Any]:
    """요약과 원문을 구분한 테스트 상세 응답을 만든다."""
    return {"success": True, "data": {
        "id": job_id(number), "title": "백엔드 개발자",
        "redirectUrl": f"https://example.com/jobs/{number}",
        "content": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]},
        "summary": {"type": "text", "text": "요약을 원문에 섞으면 안 됩니다."},
    }}


def page(number: int, ids: tuple[int, ...], last: bool = False) -> dict[str, Any]:
    """페이지 경계와 마지막 여부를 포함한 목록 응답을 만든다."""
    return {"success": True, "data": {"page": number, "content": [listing(i) for i in ids], "last": last, "totalElements": 10}}


def test_rich_text_preserves_inline_and_paragraph_boundaries() -> None:
    """인라인 서식 때문에 단어가 갈라지거나 문단이 붙지 않는지 검증한다."""
    node = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Py"}, {"type": "text", "text": "thon 개발"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "지원 조건"}]},
    ]}
    assert crawler.rich_text(node) == "Python 개발\n지원 조건\n"


def test_summary_fallback_is_labeled() -> None:
    """빈 원문은 요약으로 보완하고 출처를 명시하는지 검증한다."""
    payload = detail(1, "")
    document = crawler.make_document(payload["data"], job_id(1), "now")
    assert document["content"] == payload["data"]["summary"]["text"]
    assert document["content_source"] == "summary"


def test_original_content_has_priority() -> None:
    """원문이 있으면 요약 대신 원문만 사용하는지 검증한다."""
    document = crawler.make_document(detail(1)["data"], job_id(1), "now")
    assert document["content"] == "Python 개발자를 채용합니다."
    assert document["content_source"] == "content"


def test_detail_id_mismatch_is_rejected() -> None:
    """다른 공고의 본문이 요청 URL에 연결되지 않는지 검증한다."""
    with pytest.raises(ValueError, match="ID"):
        crawler.make_document(detail(2)["data"], job_id(1), "now")


def test_page_dedup_and_transaction_rollback(tmp_path: Path) -> None:
    """겹치는 공고를 중복 저장하지 않고 반복 페이지는 체크포인트까지 롤백한다."""
    db = crawler.open_store(tmp_path)
    try:
        crawler.save_page(db, page(0, (1, 2)), 0, ("서버_백엔드",))
        crawler.save_page(db, page(1, (2, 3)), 1, ("서버_백엔드",))
        assert crawler.counts(db) == {"pending": 3}
        with pytest.raises(ValueError, match="반복 페이지"):
            crawler.save_page(db, page(2, (2, 3)), 2, ("서버_백엔드",))
        assert crawler.get_metadata(db, "next_page") == 2
        assert db.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 2
    finally:
        db.close()


def test_unfiltered_page_is_not_committed(tmp_path: Path) -> None:
    """필터가 무시된 응답은 데이터셋에 들어가지 않는지 검증한다."""
    db = crawler.open_store(tmp_path)
    try:
        with pytest.raises(ValueError, match="IT 필터"):
            crawler.save_page(db, page(0, (1,)), 0, ("프론트엔드",))
        assert crawler.counts(db) == {}
    finally:
        db.close()


def test_empty_content_and_external_duplicates_are_excluded(tmp_path: Path) -> None:
    """빈 원문과 동일 원본 URL의 재등록 공고를 제외한다."""
    db = crawler.open_store(tmp_path)
    try:
        crawler.save_page(db, page(0, (1, 2, 3)), 0, ("서버_백엔드",))
        assert crawler.save_detail(db, job_id(1), detail(1)) == "success"
        duplicate = {"success": True, "data": {**detail(2)["data"], "redirectUrl": "https://example.com/jobs/1"}}
        assert crawler.save_detail(db, job_id(2), duplicate) == "excluded"
        empty = {"success": True, "data": {**detail(3, "")["data"], "summary": None}}
        assert crawler.save_detail(db, job_id(3), empty) == "excluded"
        report = crawler.export_dataset(db, tmp_path, 3)
        assert report["exported"] == 1
        assert report["target_reached"] is False
        assert len((tmp_path / "raw_details.jsonl").read_text().splitlines()) == 3
    finally:
        db.close()


def test_resume_after_interrupt_keeps_completed_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """상세 수집 중 중단 후 기존 성공 공고와 목록을 재요청하지 않는다."""
    categories = {"success": True, "data": [{"name": "IT_개발", "depthTwos": ["서버_백엔드"]}]}
    first = Mock(side_effect=[categories, page(0, (1, 2), True), detail(1), KeyboardInterrupt])
    monkeypatch.setattr(crawler, "request_json", first)
    with pytest.raises(KeyboardInterrupt):
        crawler.crawl(tmp_path, 2, 0.1)
    assert len((tmp_path / "corpus.jsonl").read_text().splitlines()) == 1
    resumed = Mock(return_value=detail(2))
    monkeypatch.setattr(crawler, "request_json", resumed)
    report = crawler.crawl(tmp_path, 2, 0.1)
    assert report["exported"] == 2
    assert resumed.call_count == 1
    assert resumed.call_args.args[1] == f"/recruitments/{job_id(2)}"
    monkeypatch.setattr(crawler, "request_json", Mock(side_effect=AssertionError("네트워크 재요청")))
    assert crawler.crawl(tmp_path, 2, 0.1)["exported"] == 2


def test_rate_limit_retries_and_honors_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    """429 응답의 대기 시간을 지킨 뒤 재요청한다."""
    sleep = Mock()
    monkeypatch.setattr(crawler.time, "sleep", sleep)
    limited = Mock(status_code=429, headers={"Retry-After": "7"})
    success = Mock(status_code=200)
    success.json.return_value = {"success": True, "data": {}}
    session = Mock(spec=requests.Session)
    session.get.side_effect = [limited, success]
    assert crawler.request_json(session, "/recruitments", 0.2)["success"] is True
    assert session.get.call_count == 2
    assert sleep.call_args_list[1].args == (7.0,)


def test_http_200_business_error_is_not_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 200이어도 API 실패 응답이면 실패로 처리한다."""
    monkeypatch.setattr(crawler.time, "sleep", Mock())
    response = Mock(status_code=200)
    response.json.return_value = {"success": False, "data": None}
    session = Mock(spec=requests.Session)
    session.get.return_value = response
    with pytest.raises(ValueError, match="API 실패"):
        crawler.request_json(session, "/recruitments", 0.2)


def test_old_checkpoint_reuses_raw_summary_without_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """이전 원문 전용 체크포인트를 원본 재요청 없이 요약 포함 방식으로 전환한다."""
    db = crawler.open_store(tmp_path)
    try:
        with db:
            crawler.put_metadata(db, "config", {"schema_version": 1, "depth_twos": ["서버_백엔드"]})
        crawler.save_page(db, page(0, (1,), True), 0, ("서버_백엔드",))
        with db:
            db.execute(
                "UPDATE jobs SET status='excluded', detail=?, fetched_at='original-time', error='empty_content'",
                (crawler.encode(detail(1, "")),),
            )
    finally:
        db.close()
    monkeypatch.setattr(crawler, "request_json", Mock(side_effect=AssertionError("네트워크 재요청")))
    report = crawler.crawl(tmp_path, 1, 0.1)
    assert report["exported"] == 1
    assert report["config"]["schema_version"] == 2
    import json
    document = json.loads((tmp_path / "corpus.jsonl").read_text())
    assert document["content_source"] == "summary"
    assert document["fetched_at"] == "original-time"
