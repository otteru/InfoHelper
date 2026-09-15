"""고정된 파일럿 후보를 로컬 웹에서 판정하고 저장한다."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'RAG_evaluation/dataset/zighang'
ARTIFACTS = ROOT / 'RAG_evaluation/artifacts/zighang_v1'
OUTPUT = Path(os.environ.get('LABELING_OUTPUT_DIR', str(ARTIFACTS / 'labeling_pilot_v1')))
app = FastAPI(title='InfoHelper 라벨링')


def read_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    """JSONL 파일을 불변 행 목록으로 읽는다."""
    return tuple(json.loads(line) for line in path.read_text().splitlines() if line.strip())


def digest(value: str) -> str:
    """고정 시드로 재현 가능한 정렬 키를 만든다."""
    return hashlib.sha256(f'pilot-v1:{value}'.encode()).hexdigest()


def prepare() -> tuple[dict[str, Any], ...]:
    """유형별 20쌍을 쿼리에 고르게 분배하고 스냅샷을 고정한다."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    snapshot = OUTPUT / 'pilot.json'
    if snapshot.exists():
        return tuple(json.loads(snapshot.read_text())['items'])
    queries = read_jsonl(DATA / 'queries/eval_queries_80.jsonl')
    documents = {row['id']: row for row in read_jsonl(DATA / 'corpus.jsonl')}
    names = ('dense_fixed1000_qwen1536_v1', 'bm25_kiwi_v1')
    runs = tuple(ARTIFACTS / 'runs' / f'{name}.jsonl' for name in names)
    pairs = frozenset((r['query_id'], r['doc_id']) for path in runs for r in read_jsonl(path))
    selected = tuple(
        (q, doc_id)
        for kind in sorted({q['type'] for q in queries})
        for _, _, q, doc_id in sorted(
            (index, digest(q['query_id']), q, doc_id)
            for q in queries if q['type'] == kind
            for index, doc_id in enumerate(sorted(
                (d for query_id, d in pairs if query_id == q['query_id']),
                key=lambda d: digest(q['query_id'] + d),
            ))
        )[:20]
    )
    items = tuple({
        'id': f"{q['query_id']}:{doc_id}", 'query_id': q['query_id'],
        'query': q['query'], 'type': q['type'], 'intent': q['intent'],
        'interpretations': q.get('interpretations', []),
        'warning': '질의는 9월 14일 이전, 작성 메모는 9월 14일 당일을 포함합니다. 경계에 걸리면 판단 보류하세요.' if q['query_id'] == 'Q046' else '',
        'doc_id': doc_id, 'document': documents[doc_id],
    } for q, doc_id in selected)
    if len(items) != 120 or len({i['id'] for i in items}) != 120:
        raise ValueError('파일럿은 중복 없는 120쌍이어야 합니다')
    sources = (DATA / 'corpus.jsonl', DATA / 'queries/eval_queries_80.jsonl', *runs)
    snapshot.write_text(json.dumps({'seed': 'pilot-v1', 'reference_date': '2026-09-07',
        'source_hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        'items': items}, ensure_ascii=False, indent=2))
    return items


ITEMS = prepare()


def connect() -> sqlite3.Connection:
    """판정 데이터베이스 연결과 테이블을 준비한다."""
    db = sqlite3.connect(OUTPUT / 'labels.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS labels (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    return db


class Judgment(BaseModel):
    """사용자가 제출한 판정과 메모."""
    label: Literal[0, 1, 2, 'review']
    note: str = Field(default='', max_length=5000)
    interpretations: list[str] = Field(default_factory=list)


@app.middleware('http')
async def local_requests(request: Request, call_next: Any) -> Response:
    """외부 사이트에서 로컬 판정을 변경하는 요청을 차단한다."""
    if request.headers.get('host', '').split(':')[0] not in ('127.0.0.1', 'localhost', 'testserver'):
        return Response(status_code=403)
    if request.method == 'POST':
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return Response(status_code=403)
        if not request.headers.get('content-type', '').startswith('application/json'):
            return Response(status_code=415)
    return await call_next(request)


@app.get('/')
def home() -> FileResponse:
    """평가 화면을 반환한다."""
    return FileResponse(Path(__file__).with_name('index.html'))


@app.get('/api/items')
def items() -> dict[str, Any]:
    """후보와 기존 판정을 함께 반환한다."""
    with connect() as db:
        labels = {key: json.loads(payload) for key, payload in db.execute('SELECT id, payload FROM labels')}
    return {'items': ITEMS, 'labels': labels}


@app.post('/api/labels/{item_id}')
def save(item_id: str, judgment: Judgment) -> dict[str, Any]:
    """유효한 후보 판정을 트랜잭션으로 저장한다."""
    item = next((row for row in ITEMS if row['id'] == item_id), None)
    if item is None:
        raise HTTPException(404, '없는 후보입니다')
    if any(value not in item['interpretations'] for value in judgment.interpretations):
        raise HTTPException(422, '허용되지 않은 해석입니다')
    payload = {**judgment.model_dump(), 'query_id': item['query_id'], 'doc_id': item['doc_id'],
               'type': item['type'], 'reviewer': 'human', 'updated_at': datetime.now(timezone.utc).isoformat()}
    with connect() as db:
        db.execute('INSERT INTO labels VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                   (item_id, json.dumps(payload, ensure_ascii=False)))
    return payload


@app.get('/api/export/{kind}')
def export(kind: Literal['json', 'qrels']) -> Response:
    """검수 상태와 요약 또는 확정 판정만 포함한 qrels를 내려준다."""
    labels = items()['labels']
    if kind == 'qrels':
        content = '\n'.join(f"{v['query_id']} 0 {v['doc_id']} {v['label']}" for _, v in sorted(labels.items()) if v['label'] != 'review') + '\n'
        media = 'text/plain'
    else:
        content = json.dumps({'total': len(ITEMS), 'unjudged': len(ITEMS) - len(labels),
            'counts': dict(Counter(str(v['label']) for v in labels.values())),
            'labels': labels}, ensure_ascii=False, indent=2)
        media = 'application/json'
    return Response(content, media_type=media, headers={'Content-Disposition': f'attachment; filename="pilot.{kind}"'})


class Alignment(BaseModel):
    """사용자가 확정한 점수와 적용 규칙 및 근거."""
    label: Literal[0, 1, 2, 'review']
    rule: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=5000)
    source_hash: str


def alignment_source() -> tuple[str, tuple[dict[str, Any], ...]]:
    """비교 결과의 큰 불일치와 고정 원문을 연결한다."""
    path = OUTPUT / 'llm_blind_v1/agent_comparison.json'
    if not path.exists():
        raise HTTPException(404, '독립 평가 비교 파일이 없습니다')
    raw = path.read_bytes()
    documents = {item['id']: item for item in ITEMS}
    rows = tuple({**row, 'document': documents[row['id']]['document'],
                  'warning': documents[row['id']].get('warning', '')}
                 for row in json.loads(raw)['rows'] if abs(row['human'] - row['agent']) == 2)
    return hashlib.sha256(raw).hexdigest(), rows


def alignment_db() -> sqlite3.Connection:
    """원래 라벨과 분리된 합의 이력 저장소를 연다."""
    db = sqlite3.connect(OUTPUT / 'alignment.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS decisions (seq INTEGER PRIMARY KEY, id TEXT NOT NULL, payload TEXT NOT NULL)')
    return db


@app.get('/align')
def alignment_page() -> FileResponse:
    """큰 불일치 검토 화면을 반환한다."""
    return FileResponse(Path(__file__).with_name('align.html'))


@app.get('/api/alignment')
def alignment_items() -> dict[str, Any]:
    """큰 불일치와 현재 원본에 대한 최신 합의 및 이력을 반환한다."""
    source_hash, rows = alignment_source()
    with alignment_db() as db:
        history = tuple({'id': key, **json.loads(payload)} for key, payload in db.execute('SELECT id, payload FROM decisions ORDER BY seq'))
    decisions = {row['id']: row for row in history if row['source_hash'] == source_hash}
    return {'source_hash': source_hash, 'items': rows, 'decisions': decisions, 'history': history}


@app.post('/api/alignment/{item_id}')
def save_alignment(item_id: str, decision: Alignment) -> dict[str, Any]:
    """합의 근거를 검증하고 기존 판정을 보존하며 새 이력을 저장한다."""
    source_hash, rows = alignment_source()
    if decision.source_hash != source_hash:
        raise HTTPException(409, '비교 원본이 바뀌었습니다. 새로고침하세요')
    if item_id not in {row['id'] for row in rows}:
        raise HTTPException(404, '검토 대상이 아닙니다')
    if not decision.rule.strip() or not decision.reason.strip():
        raise HTTPException(422, '적용 규칙과 근거를 입력하세요')
    payload = {**decision.model_dump(), 'reviewer': 'human', 'updated_at': datetime.now(timezone.utc).isoformat()}
    with alignment_db() as db:
        db.execute('INSERT INTO decisions(id,payload) VALUES (?,?)', (item_id, json.dumps(payload, ensure_ascii=False)))
    return {'id': item_id, **payload}


@app.get('/api/alignment-export')
def export_alignment() -> Response:
    """원문과 양쪽 판정 및 합의 이력을 JSON으로 내려준다."""
    return Response(json.dumps(alignment_items(), ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition': 'attachment; filename="alignment.json"'})
