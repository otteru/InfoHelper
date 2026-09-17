"""직행 IT·개발 공고의 원문·요약을 재개 가능한 평가 데이터셋으로 수집한다."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import requests

API = "https://api.zighang.com/api"
SOURCE_URL = "https://zighang.com/it"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "dataset" / "zighang"
PAGE_SIZE = 20
SCHEMA_VERSION = 2
TEXT_POLICY = "content 원문 우선; 빈 원문은 summary 사용; 둘 다 빈 경우 제외"


def now() -> str:
    """수집 시각을 UTC ISO 형식으로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def encode(value: Any) -> str:
    """한글을 유지한 JSON 문자열로 직렬화한다."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def request_json(
    session: requests.Session,
    path: str,
    delay: float,
    params: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    """속도 제한과 일시적 오류 재시도를 적용해 공개 API 응답을 검증한다."""
    for attempt in range(4):
        time.sleep(delay)
        try:
            response = session.get(API + path, params=params, timeout=(10, 30))
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 3:
                    retry_after = response.headers.get("Retry-After", "")
                    wait = float(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1)
                    time.sleep(max(wait, 2 ** (attempt + 1)))
                    continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("success") is not True:
                raise ValueError(f"API 실패: {str(payload)[:300]}")
            if payload.get("data") is None:
                raise ValueError("API data가 없습니다.")
            return payload
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError("API 재시도 횟수를 초과했습니다.")


def open_store(output: Path) -> sqlite3.Connection:
    """원본·진행 상태·정제 문서를 저장하는 로컬 체크포인트를 연다."""
    output.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(output / "checkpoint.sqlite3", timeout=1)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS pages (
            page INTEGER PRIMARY KEY, fetched_at TEXT NOT NULL, response TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT NOT NULL UNIQUE, listing TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            detail TEXT, document TEXT, external_url TEXT,
            fetched_at TEXT, error TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS unique_external_url
            ON jobs(external_url) WHERE status = 'success' AND external_url IS NOT NULL;
    """)
    return db


def get_metadata(db: sqlite3.Connection, key: str) -> Any:
    """저장된 체크포인트 값을 읽는다."""
    row = db.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else None


def put_metadata(db: sqlite3.Connection, key: str, value: Any) -> None:
    """호출자의 트랜잭션 안에서 체크포인트 값을 저장한다."""
    db.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?)", (key, encode(value)))


def initialize(db: sqlite3.Connection, session: requests.Session, delay: float) -> dict[str, Any]:
    """최초 실행의 IT 직무 필터와 정렬 조건을 고정해 재개 시 재사용한다."""
    saved = get_metadata(db, "config")
    if saved:
        if saved.get("schema_version") == 1:
            for row in db.execute("SELECT id, detail, fetched_at FROM jobs WHERE detail IS NOT NULL ORDER BY seq").fetchall():
                save_detail(db, row["id"], json.loads(row["detail"]), row["fetched_at"])
            upgraded = {**saved, "schema_version": SCHEMA_VERSION, "text_policy": TEXT_POLICY}
            with db:
                put_metadata(db, "config", upgraded)
            return upgraded
        if saved.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("체크포인트 버전이 다릅니다. 새 출력 폴더를 사용하세요.")
        return saved
    payload = request_json(session, "/recruitments/job-categories", delay)
    categories = payload["data"]
    category = next(item for item in categories if item["name"] == "IT_개발")
    filters = category["depthTwos"]
    if not filters or not all(isinstance(value, str) and value for value in filters):
        raise ValueError("IT·개발 필터가 비어 있거나 올바르지 않습니다.")
    config = {
        "schema_version": SCHEMA_VERSION, "source_url": SOURCE_URL,
        "api_url": API, "started_at": now(), "depth_twos": filters,
        "sort_condition": "LATEST", "order_condition": "DESC", "page_size": PAGE_SIZE,
        "text_policy": TEXT_POLICY,
    }
    with db:
        put_metadata(db, "config", config)
        put_metadata(db, "categories_response", payload)
        put_metadata(db, "next_page", 0)
        put_metadata(db, "exhausted", False)
    return config


def save_page(db: sqlite3.Connection, payload: dict[str, Any], page: int, filters: tuple[str, ...]) -> None:
    """페이지 원본·고유 공고·다음 페이지를 하나의 트랜잭션으로 저장한다."""
    data = payload["data"]
    if not isinstance(data, dict) or data.get("page") != page:
        raise ValueError("응답 페이지가 요청과 다릅니다.")
    items = data.get("content")
    if not isinstance(items, list) or not isinstance(data.get("last"), bool):
        raise ValueError("목록 API 응답 구조가 변경됐습니다.")
    if not items and not data["last"]:
        raise ValueError("마지막 페이지가 아닌데 목록이 비어 있습니다.")
    for item in items:
        UUID(item["id"])
        if not set(item.get("depthTwos", ())).intersection(filters):
            raise ValueError("IT 필터에 속하지 않는 공고가 반환됐습니다.")
    with db:
        before = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        db.execute("INSERT INTO pages VALUES (?, ?, ?)", (page, now(), encode(payload)))
        db.executemany(
            "INSERT OR IGNORE INTO jobs(id, listing) VALUES (?, ?)",
            ((item["id"], encode(item)) for item in items),
        )
        after = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        if items and after == before and not data["last"]:
            raise ValueError("새 공고가 없는 반복 페이지입니다. 수집을 중단합니다.")
        put_metadata(db, "next_page", page + 1)
        put_metadata(db, "exhausted", data["last"])
        put_metadata(db, "latest_total_elements", data["totalElements"])


def rich_text(node: Any) -> str:
    """Tiptap 원문에서 문단 경계와 인라인 공백을 보존한 텍스트를 추출한다."""
    if node is None:
        return ""
    if not isinstance(node, dict):
        raise ValueError("지원하지 않는 원문 형식입니다.")
    kind = node.get("type")
    if kind == "text":
        text = node.get("text", "")
        if not isinstance(text, str):
            raise ValueError("원문 text 필드가 문자열이 아닙니다.")
        return text
    if kind == "hardBreak":
        return "\n"
    children = node.get("content", [])
    if not isinstance(children, list):
        raise ValueError("원문 하위 content가 배열이 아닙니다.")
    text = "".join(rich_text(child) for child in children)
    return text + ("\n" if kind in {"paragraph", "heading", "listItem", "blockquote", "codeBlock", "tableRow"} else "\t" if kind in {"tableCell", "tableHeader"} else "")


def image_urls(node: Any) -> tuple[str, ...]:
    """텍스트와 함께 있거나 원문을 대신하는 이미지 주소를 보존한다."""
    if not isinstance(node, dict):
        return ()
    own = (node["attrs"]["src"],) if node.get("type") == "image" and node.get("attrs", {}).get("src") else ()
    return own + tuple(url for child in node.get("content", []) for url in image_urls(child))


def make_document(detail: dict[str, Any], expected_id: str, fetched_at: str) -> dict[str, Any]:
    """상세 ID를 대조하고 원문 우선·요약 대체 정책으로 평가 문서를 만든다."""
    if detail.get("id") != expected_id:
        raise ValueError("요청 공고 ID와 상세 응답 ID가 다릅니다.")
    title = detail.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("상세 제목이 비어 있습니다.")
    content = "\n".join(line.strip() for line in rich_text(detail.get("content")).splitlines() if line.strip())
    content_source = "content" if content else "summary"
    if not content:
        content = "\n".join(line.strip() for line in rich_text(detail.get("summary")).splitlines() if line.strip())
    return {
        "id": expected_id, "url": f"https://zighang.com/recruitment/{expected_id}",
        "title": title.strip(), "content": content, "content_source": content_source,
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "image_urls": image_urls(detail.get("content")),
        "fetched_at": fetched_at,
        "metadata": {key: detail.get(key) for key in (
            "company", "affiliate", "redirectUrl", "createdAt", "endDate", "deadlineType",
            "status", "careerMin", "careerMax", "regions", "employeeTypes", "educations",
            "depthOnes", "depthTwos", "keywords",
        )},
    }


def save_detail(
    db: sqlite3.Connection, job_id: str, payload: dict[str, Any], fetched_at: str | None = None,
) -> str:
    """원본 응답과 정제 결과를 저장하고 빈 본문·외부 URL 중복을 제외한다."""
    fetched_at = fetched_at or now()
    with db:
        db.execute(
            "UPDATE jobs SET detail=?, fetched_at=? WHERE id=?",
            (encode(payload), fetched_at, job_id),
        )
    document = make_document(payload["data"], job_id, fetched_at)
    external_url = payload["data"].get("redirectUrl") or None
    duplicate = external_url and db.execute(
        "SELECT 1 FROM jobs WHERE external_url = ? AND status = 'success' AND id != ?",
        (external_url, job_id),
    ).fetchone()
    reason = "empty_content" if not document["content"] else "duplicate_external_url" if duplicate else None
    status = "excluded" if reason else "success"
    with db:
        db.execute(
            "UPDATE jobs SET status=?, detail=?, document=?, external_url=?, fetched_at=?, error=? WHERE id=?",
            (status, encode(payload), encode(document) if not reason else None, external_url, fetched_at, reason, job_id),
        )
    return status


def counts(db: sqlite3.Connection) -> dict[str, int]:
    """성공·제외·실패·대기 공고 수를 집계한다."""
    return {row["status"]: row["n"] for row in db.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")}


def export_dataset(db: sqlite3.Connection, output: Path, limit: int) -> dict[str, Any]:
    """평가용 JSONL과 원본·실패 기록·품질 보고서를 원자적으로 내보낸다."""
    queries = {
        "corpus.jsonl": ("SELECT document AS value FROM jobs WHERE status='success' ORDER BY seq LIMIT ?", (limit,)),
        "raw_details.jsonl": ("SELECT detail AS value FROM jobs WHERE detail IS NOT NULL ORDER BY seq", ()),
        "raw_pages.jsonl": ("SELECT response AS value FROM pages ORDER BY page", ()),
    }
    for filename, (query, params) in queries.items():
        temporary = output / (filename + ".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            for row in db.execute(query, params):
                stream.write(row["value"] + "\n")
        temporary.replace(output / filename)
    issues = tuple(dict(row) for row in db.execute("SELECT id, status, error FROM jobs WHERE status IN ('error', 'excluded') ORDER BY seq"))
    report = {
        "config": get_metadata(db, "config"), "updated_at": now(), "target": limit,
        "counts": counts(db), "exported": min(limit, counts(db).get("success", 0)),
        "next_page": get_metadata(db, "next_page"), "exhausted": get_metadata(db, "exhausted"),
        "latest_total_elements": get_metadata(db, "latest_total_elements"),
        "target_reached": counts(db).get("success", 0) >= limit,
        "exclusion_reasons": {row["error"]: row["n"] for row in db.execute("SELECT error, COUNT(*) AS n FROM jobs WHERE status='excluded' GROUP BY error")},
    }
    for filename, value in (("issues.json", issues), ("report.json", report)):
        temporary = output / (filename + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output / filename)
    return report


def crawl(output: Path, limit: int, delay: float, export_only: bool = False) -> dict[str, Any]:
    """저장된 페이지와 상세 상태에서 재개해 목표 개수의 공고를 수집한다."""
    output.mkdir(parents=True, exist_ok=True)
    lock = (output / ".crawler.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError("같은 출력 폴더에서 다른 수집기가 실행 중입니다.") from None
    db = open_store(output)
    try:
        with requests.Session() as session:
            session.headers.update({"User-Agent": "InfoHelper-RAGEvaluation/1.0", "Accept": "application/json"})
            if export_only:
                if not get_metadata(db, "config"):
                    raise ValueError("수집된 체크포인트가 없습니다.")
                return export_dataset(db, output, limit)
            config = initialize(db, session, delay)
            with db:
                db.execute("UPDATE jobs SET status='pending' WHERE status='error'")
            failures = 0
            while counts(db).get("success", 0) < limit:
                job = db.execute("SELECT id FROM jobs WHERE status='pending' ORDER BY seq LIMIT 1").fetchone()
                if job:
                    try:
                        payload = request_json(session, f"/recruitments/{job['id']}", delay)
                        save_detail(db, job["id"], payload)
                        failures = 0
                    except (requests.RequestException, ValueError) as exc:
                        if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code in {401, 403, 429}:
                            raise
                        with db:
                            db.execute("UPDATE jobs SET status='error', error=? WHERE id=?", (str(exc)[:500], job["id"]))
                        failures += 1
                        if failures >= 5:
                            raise RuntimeError("상세 수집이 연속 5회 실패해 중단합니다.") from exc
                    continue
                if get_metadata(db, "exhausted"):
                    break
                page = get_metadata(db, "next_page")
                params = tuple(("depthTwos", value) for value in config["depth_twos"]) + (
                    ("page", str(page)), ("size", str(PAGE_SIZE)),
                    ("sortCondition", config["sort_condition"]), ("orderCondition", config["order_condition"]),
                )
                payload = request_json(session, "/recruitments", delay, params)
                save_page(db, payload, page, tuple(config["depth_twos"]))
                print(encode({"page": page, "total": payload["data"]["totalElements"], **counts(db)}), flush=True)
        return export_dataset(db, output, limit)
    finally:
        if get_metadata(db, "config"):
            export_dataset(db, output, limit)
        db.close()
        lock.close()


def main() -> None:
    """명령행 옵션을 검증하고 수집 결과를 출력한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5000, help="원문 또는 요약이 있는 공고 목표 건수")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--delay", type=float, default=0.2, help="각 요청 전 대기 초 (최소 0.1)")
    parser.add_argument("--export-only", action="store_true")
    args = parser.parse_args()
    if args.limit < 1 or args.delay < 0.1:
        parser.error("limit는 양수, delay는 0.1초 이상이어야 합니다.")
    try:
        report = crawl(args.output, args.limit, args.delay, args.export_only)
    except KeyboardInterrupt:
        print("중단했습니다. 같은 명령으로 재개할 수 있습니다.")
        raise SystemExit(130)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["target_reached"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
