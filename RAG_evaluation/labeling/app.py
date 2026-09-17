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
DATA = ROOT / 'RAG_evaluation/dataset'
ARTIFACTS = ROOT / 'RAG_evaluation/artifacts/zighang_v1'
OUTPUT = Path(os.environ.get('LABELING_OUTPUT_DIR', str(ARTIFACTS / 'labeling_pilot_v1')))
HOLDOUT_OUTPUT = Path(os.environ.get('LABELING_HOLDOUT_DIR', str(ARTIFACTS / 'labeling_holdout_v1')))
FIRST_PASS = Path(os.environ.get('LABELING_FIRST_PASS_DIR', str(ARTIFACTS / 'labeling_first_pass_v1')))
ALIGNED = Path(os.environ.get(
    'LABELING_ALIGNED_DIR',
    str(ROOT / 'RAG_evaluation/dataset/labeling/pilot_aligned_v1'),
))
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


def select_stratified(
    queries: tuple[dict[str, Any], ...],
    pairs: frozenset[tuple[str, str]],
    count: int,
) -> tuple[tuple[dict[str, Any], str], ...]:
    """유형별 count쌍을 쿼리 라운드 로빈으로 고른다."""
    return tuple(
        (q, doc_id)
        for kind in sorted({q['type'] for q in queries})
        for _, _, q, doc_id in sorted(
            (index, digest(q['query_id']), q, doc_id)
            for q in queries if q['type'] == kind
            for index, doc_id in enumerate(sorted(
                (d for query_id, d in pairs if query_id == q['query_id']),
                key=lambda d: digest(q['query_id'] + d),
            ))
        )[:count]
    )


def excluded_pilot_ids() -> frozenset[str]:
    """파일럿 120쌍 ID를 모아 holdout에서 뺀다."""
    ids = {item['id'] for item in ITEMS}
    aligned = ROOT / 'RAG_evaluation/dataset/labeling/pilot_aligned_v2/pairs.jsonl'
    if aligned.exists():
        ids = ids | {json.loads(line)['pair_id'] for line in aligned.read_text().splitlines() if line.strip()}
    return frozenset(ids)


def holdout_warning(query_id: str) -> str:
    """확정된 날짜 규칙을 해당 질의에만 짧게 안내한다."""
    if query_id == 'Q046':
        return '9월 14일 이전은 당일 제외입니다. 마감이 14일이면 이 조건은 위반입니다.'
    if query_id == 'Q075':
        return '2020년 이전은 게시일(createdAt) 기준입니다. 수집일로 판단하지 마세요.'
    return ''


def prepare_holdout() -> tuple[dict[str, Any], ...]:
    """파일럿과 겹치지 않는 유형별 20쌍을 고정한다."""
    HOLDOUT_OUTPUT.mkdir(parents=True, exist_ok=True)
    snapshot = HOLDOUT_OUTPUT / 'holdout.json'
    if snapshot.exists():
        return tuple(json.loads(snapshot.read_text())['items'])
    queries = read_jsonl(DATA / 'queries/eval_queries_80.jsonl')
    documents = {row['id']: row for row in read_jsonl(DATA / 'corpus.jsonl')}
    names = ('dense_fixed1000_qwen1536_v1', 'bm25_kiwi_v1')
    runs = tuple(ARTIFACTS / 'runs' / f'{name}.jsonl' for name in names)
    excluded = excluded_pilot_ids()
    pairs = frozenset(
        (r['query_id'], r['doc_id'])
        for path in runs for r in read_jsonl(path)
        if f"{r['query_id']}:{r['doc_id']}" not in excluded
    )
    selected = select_stratified(queries, pairs, 20)
    items = tuple({
        'id': f"{q['query_id']}:{doc_id}", 'query_id': q['query_id'],
        'query': q['query'], 'type': q['type'], 'intent': q['intent'],
        'interpretations': q.get('interpretations', []),
        'warning': holdout_warning(q['query_id']),
        'doc_id': doc_id, 'document': documents[doc_id],
    } for q, doc_id in selected)
    if len(items) != 120 or len({i['id'] for i in items}) != 120:
        raise ValueError('holdout은 중복 없는 120쌍이어야 합니다')
    if {i['id'] for i in items} & excluded:
        raise ValueError('holdout은 파일럿 쌍과 겹치면 안 됩니다')
    sources = (DATA / 'corpus.jsonl', DATA / 'queries/eval_queries_80.jsonl', *runs)
    snapshot.write_text(json.dumps({
        'seed': 'pilot-v1', 'sample': 'holdout-v1', 'reference_date': '2026-09-07',
        'excluded_count': len(excluded),
        'source_hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        'items': items,
    }, ensure_ascii=False, indent=2))
    return items


HOLDOUT_ITEMS = prepare_holdout()


def prepare_review() -> tuple[dict[str, Any], ...]:
    """Grok 1차에서 검수 표시된 쌍만 공고 원문과 붙인다."""
    remaining = {row['id']: row for row in read_jsonl(FIRST_PASS / 'remaining.jsonl')}
    return tuple(
        {
            **remaining[row['id']],
            'grok_label': row['label'],
            'grok_reason': row.get('reason') or '',
            'grok_flags': tuple(row.get('flags') or ()),
            'grok_evidence': tuple(row.get('evidence') or ()),
            'grok_confidence': row.get('confidence') or '',
        }
        for row in read_jsonl(FIRST_PASS / 'grok_v1/judgments.jsonl')
        if row.get('review') and row['id'] in remaining
    )


REVIEW_ITEMS = prepare_review()


def take_round_robin(rows: tuple[dict[str, Any], ...], count: int) -> tuple[dict[str, Any], ...]:
    """쿼리 라운드 로빈으로 count개를 고른다."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda item: (digest(item['query_id']), digest(item['id']))):
        grouped.setdefault(row['query_id'], []).append(row)
    queries = tuple(sorted(grouped, key=digest))
    picked: list[dict[str, Any]] = []
    depth = 0
    while len(picked) < count and queries:
        progressed = False
        for query_id in queries:
            bucket = grouped[query_id]
            if depth < len(bucket):
                picked.append(bucket[depth])
                progressed = True
                if len(picked) == count:
                    return tuple(picked)
        if not progressed:
            break
        depth += 1
    return tuple(picked)


def prepare_audit() -> tuple[dict[str, Any], ...]:
    """자동 통과 2,429건에서 유형·0/2가 고른 50쌍을 고정한다."""
    snapshot = FIRST_PASS / 'audit.json'
    if snapshot.exists():
        return tuple(json.loads(snapshot.read_text())['items'])
    remaining = {row['id']: row for row in read_jsonl(FIRST_PASS / 'remaining.jsonl')}
    auto = tuple(
        {
            **remaining[row['id']],
            'grok_label': row['label'],
            'grok_reason': row.get('reason') or '',
            'grok_flags': tuple(row.get('flags') or ()),
            'grok_evidence': tuple(row.get('evidence') or ()),
            'grok_confidence': row.get('confidence') or '',
        }
        for row in read_jsonl(FIRST_PASS / 'grok_v1/judgments.jsonl')
        if not row.get('review') and row['id'] in remaining and row['label'] in (0, 2)
    )
    zeros = tuple(row for row in auto if row['grok_label'] == 0)
    twos = tuple(row for row in auto if row['grok_label'] == 2)
    zero_types = tuple(sorted({row['type'] for row in zeros}))
    two_types = tuple(sorted({row['type'] for row in twos}))
    picked_zeros = tuple(
        item
        for kind in zero_types
        for item in take_round_robin(tuple(row for row in zeros if row['type'] == kind), 4 if kind != zero_types[-1] else 5)
    )
    picked_twos = tuple(
        item
        for kind in two_types
        for item in take_round_robin(tuple(row for row in twos if row['type'] == kind), 5)
    )
    items = picked_zeros + picked_twos
    if len(items) != 50 or len({row['id'] for row in items}) != 50:
        raise ValueError(f'감사 표본이 50쌍이 아닙니다: {len(items)}')
    snapshot.write_text(json.dumps({
        'sample': 'audit-50-v1', 'count': len(items),
        'score_counts': dict(Counter(str(row['grok_label']) for row in items)),
        'type_counts': dict(Counter(row['type'] for row in items)),
        'items': items,
    }, ensure_ascii=False, indent=2))
    return items


AUDIT_ITEMS = prepare_audit()


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


def holdout_connect() -> sqlite3.Connection:
    """holdout 판정 데이터베이스 연결과 테이블을 준비한다."""
    HOLDOUT_OUTPUT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(HOLDOUT_OUTPUT / 'labels.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS labels (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    return db


@app.get('/holdout')
def holdout_page() -> FileResponse:
    """holdout 평가 화면을 반환한다."""
    return FileResponse(Path(__file__).with_name('index.html'))


@app.get('/api/holdout/items')
def holdout_items() -> dict[str, Any]:
    """holdout 후보와 기존 판정을 함께 반환한다."""
    with holdout_connect() as db:
        labels = {key: json.loads(payload) for key, payload in db.execute('SELECT id, payload FROM labels')}
    return {'items': HOLDOUT_ITEMS, 'labels': labels}


@app.post('/api/holdout/labels/{item_id}')
def save_holdout(item_id: str, judgment: Judgment) -> dict[str, Any]:
    """유효한 holdout 후보 판정을 트랜잭션으로 저장한다."""
    item = next((row for row in HOLDOUT_ITEMS if row['id'] == item_id), None)
    if item is None:
        raise HTTPException(404, '없는 후보입니다')
    if any(value not in item['interpretations'] for value in judgment.interpretations):
        raise HTTPException(422, '허용되지 않은 해석입니다')
    payload = {**judgment.model_dump(), 'query_id': item['query_id'], 'doc_id': item['doc_id'],
               'type': item['type'], 'reviewer': 'human', 'updated_at': datetime.now(timezone.utc).isoformat()}
    with holdout_connect() as db:
        db.execute('INSERT INTO labels VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                   (item_id, json.dumps(payload, ensure_ascii=False)))
    return payload


@app.get('/api/holdout/export/{kind}')
def export_holdout(kind: Literal['json', 'qrels']) -> Response:
    """holdout 검수 상태와 요약 또는 확정 판정만 포함한 qrels를 내려준다."""
    labels = holdout_items()['labels']
    if kind == 'qrels':
        content = '\n'.join(f"{v['query_id']} 0 {v['doc_id']} {v['label']}" for _, v in sorted(labels.items()) if v['label'] != 'review') + '\n'
        media = 'text/plain'
    else:
        content = json.dumps({'total': len(HOLDOUT_ITEMS), 'unjudged': len(HOLDOUT_ITEMS) - len(labels),
            'counts': dict(Counter(str(v['label']) for v in labels.values())),
            'labels': labels}, ensure_ascii=False, indent=2)
        media = 'application/json'
    return Response(content, media_type=media, headers={'Content-Disposition': f'attachment; filename="holdout.{kind}"'})


def review_connect() -> sqlite3.Connection:
    """1차 검수 이력을 Grok 판정 파일과 분리해 연다."""
    FIRST_PASS.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(FIRST_PASS / 'review.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS labels (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    return db


@app.get('/review')
def review_page() -> FileResponse:
    """Grok 1차 검수 화면을 반환한다."""
    return FileResponse(Path(__file__).with_name('index.html'))


@app.get('/api/review/items')
def review_items() -> dict[str, Any]:
    """검수 대상과 사람 확정을 함께 반환한다."""
    with review_connect() as db:
        labels = {key: json.loads(payload) for key, payload in db.execute('SELECT id, payload FROM labels')}
    return {'items': REVIEW_ITEMS, 'labels': labels}


@app.post('/api/review/labels/{item_id}')
def save_review(item_id: str, judgment: Judgment) -> dict[str, Any]:
    """검수 점수를 저장하고 Grok 1차 파일은 보존한다."""
    item = next((row for row in REVIEW_ITEMS if row['id'] == item_id), None)
    if item is None:
        raise HTTPException(404, '검수 대상이 아닙니다')
    if any(value not in item['interpretations'] for value in judgment.interpretations):
        raise HTTPException(422, '허용되지 않은 해석입니다')
    payload = {**judgment.model_dump(), 'query_id': item['query_id'], 'doc_id': item['doc_id'],
               'type': item['type'], 'reviewer': 'human', 'updated_at': datetime.now(timezone.utc).isoformat()}
    with review_connect() as db:
        db.execute('INSERT INTO labels VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                   (item_id, json.dumps(payload, ensure_ascii=False)))
    return payload


@app.get('/api/review/export/{kind}')
def export_review(kind: Literal['json', 'qrels']) -> Response:
    """검수 상태와 확정 점수만 포함한 qrels를 내려준다."""
    labels = review_items()['labels']
    if kind == 'qrels':
        content = '\n'.join(f"{v['query_id']} 0 {v['doc_id']} {v['label']}" for _, v in sorted(labels.items()) if v['label'] != 'review') + '\n'
        media = 'text/plain'
    else:
        content = json.dumps({'total': len(REVIEW_ITEMS), 'unjudged': len(REVIEW_ITEMS) - len(labels),
            'counts': dict(Counter(str(v['label']) for v in labels.values())),
            'labels': labels}, ensure_ascii=False, indent=2)
        media = 'application/json'
    return Response(content, media_type=media, headers={'Content-Disposition': f'attachment; filename="review.{kind}"'})


def audit_connect() -> sqlite3.Connection:
    """자동 통과 표본 검수 이력을 1차 판정과 분리해 연다."""
    FIRST_PASS.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(FIRST_PASS / 'audit.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS labels (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    return db


@app.get('/audit')
def audit_page() -> FileResponse:
    """자동 통과 50건 검수 화면을 반환한다."""
    return FileResponse(Path(__file__).with_name('index.html'))


@app.get('/api/audit/items')
def audit_items() -> dict[str, Any]:
    """감사 표본과 사람 확정을 함께 반환한다."""
    with audit_connect() as db:
        labels = {key: json.loads(payload) for key, payload in db.execute('SELECT id, payload FROM labels')}
    return {'items': AUDIT_ITEMS, 'labels': labels}


@app.post('/api/audit/labels/{item_id}')
def save_audit(item_id: str, judgment: Judgment) -> dict[str, Any]:
    """감사 점수를 저장하고 Grok 1차 파일은 보존한다."""
    item = next((row for row in AUDIT_ITEMS if row['id'] == item_id), None)
    if item is None:
        raise HTTPException(404, '감사 대상이 아닙니다')
    if any(value not in item['interpretations'] for value in judgment.interpretations):
        raise HTTPException(422, '허용되지 않은 해석입니다')
    payload = {**judgment.model_dump(), 'query_id': item['query_id'], 'doc_id': item['doc_id'],
               'type': item['type'], 'reviewer': 'human', 'updated_at': datetime.now(timezone.utc).isoformat()}
    with audit_connect() as db:
        db.execute('INSERT INTO labels VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                   (item_id, json.dumps(payload, ensure_ascii=False)))
    return payload


@app.get('/api/audit/export/{kind}')
def export_audit(kind: Literal['json', 'qrels']) -> Response:
    """감사 검수 상태와 확정 점수만 포함한 qrels를 내려준다."""
    labels = audit_items()['labels']
    if kind == 'qrels':
        content = '\n'.join(f"{v['query_id']} 0 {v['doc_id']} {v['label']}" for _, v in sorted(labels.items()) if v['label'] != 'review') + '\n'
        media = 'text/plain'
    else:
        content = json.dumps({'total': len(AUDIT_ITEMS), 'unjudged': len(AUDIT_ITEMS) - len(labels),
            'counts': dict(Counter(str(v['label']) for v in labels.values())),
            'labels': labels}, ensure_ascii=False, indent=2)
        media = 'application/json'
    return Response(content, media_type=media, headers={'Content-Disposition': f'attachment; filename="audit.{kind}"'})


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


def holdout_alignment_source() -> tuple[str, tuple[dict[str, Any], ...]]:
    """holdout 비교의 큰 불일치와 고정 원문을 연결한다."""
    path = HOLDOUT_OUTPUT / 'llm_blind_v1/agent_comparison.json'
    if not path.exists():
        raise HTTPException(404, 'holdout 독립 평가 비교 파일이 없습니다')
    raw = path.read_bytes()
    documents = {item['id']: item for item in HOLDOUT_ITEMS}
    rows = tuple({**row, 'document': documents[row['id']]['document'],
                  'warning': documents[row['id']].get('warning', '')}
                 for row in json.loads(raw)['rows'] if abs(row['human'] - row['agent']) == 2)
    return hashlib.sha256(raw).hexdigest(), rows


def holdout_alignment_db() -> sqlite3.Connection:
    """holdout 사람 라벨과 분리된 합의 이력을 연다."""
    HOLDOUT_OUTPUT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(HOLDOUT_OUTPUT / 'alignment.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS decisions (seq INTEGER PRIMARY KEY, id TEXT NOT NULL, payload TEXT NOT NULL)')
    return db


@app.get('/holdout-align')
def holdout_alignment_page() -> FileResponse:
    """holdout 큰 불일치 검토 화면을 반환한다."""
    return FileResponse(Path(__file__).with_name('align.html'))


@app.get('/api/holdout-alignment')
def holdout_alignment_items() -> dict[str, Any]:
    """holdout 큰 불일치와 최신 합의 및 이력을 반환한다."""
    source_hash, rows = holdout_alignment_source()
    with holdout_alignment_db() as db:
        history = tuple({'id': key, **json.loads(payload)} for key, payload in db.execute('SELECT id, payload FROM decisions ORDER BY seq'))
    decisions = {row['id']: row for row in history if row['source_hash'] == source_hash}
    return {'source_hash': source_hash, 'items': rows, 'decisions': decisions, 'history': history}


@app.post('/api/holdout-alignment/{item_id}')
def save_holdout_alignment(item_id: str, decision: Alignment) -> dict[str, Any]:
    """holdout 합의 근거를 검증하고 기존 사람 라벨은 보존하며 새 이력을 저장한다."""
    source_hash, rows = holdout_alignment_source()
    if decision.source_hash != source_hash:
        raise HTTPException(409, '비교 원본이 바뀌었습니다. 새로고침하세요')
    if item_id not in {row['id'] for row in rows}:
        raise HTTPException(404, '검토 대상이 아닙니다')
    if not decision.rule.strip() or not decision.reason.strip():
        raise HTTPException(422, '적용 규칙과 근거를 입력하세요')
    payload = {**decision.model_dump(), 'reviewer': 'human', 'updated_at': datetime.now(timezone.utc).isoformat()}
    with holdout_alignment_db() as db:
        db.execute('INSERT INTO decisions(id,payload) VALUES (?,?)', (item_id, json.dumps(payload, ensure_ascii=False)))
    return {'id': item_id, **payload}


@app.get('/api/holdout-alignment-export')
def export_holdout_alignment() -> Response:
    """holdout 합의 원문과 이력을 JSON으로 내려준다."""
    return Response(json.dumps(holdout_alignment_items(), ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition': 'attachment; filename="holdout-alignment.json"'})


class Confirmation(BaseModel):
    """사용자가 제안에 대해 확정한 점수와 근거."""
    label: Literal[0, 1, 2, 'review']
    reason: str = Field(min_length=1, max_length=5000)
    source_hash: str


def proposal_source() -> tuple[str, tuple[dict[str, Any], ...]]:
    """확인이 남은 제안 쌍과 고정 원문을 연결한다."""
    path = ALIGNED / 'pairs.jsonl'
    if not path.exists():
        raise HTTPException(404, '합의 데이터셋이 없습니다')
    raw = path.read_bytes()
    extras = {item['id']: item for item in ITEMS}
    rows = tuple(
        {
            **row,
            'id': row['pair_id'],
            'intent': extras.get(row['pair_id'], {}).get('intent', ''),
            'warning': extras.get(row['pair_id'], {}).get('warning', ''),
        }
        for row in (json.loads(line) for line in raw.decode().splitlines() if line.strip())
        if row.get('requires_confirmation')
    )
    return hashlib.sha256(raw).hexdigest(), rows


def confirmation_db() -> sqlite3.Connection:
    """원본 라벨·합의와 분리된 제안 확정 이력을 연다."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(OUTPUT / 'confirmation.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS decisions (seq INTEGER PRIMARY KEY, id TEXT NOT NULL, payload TEXT NOT NULL)')
    return db


@app.get('/confirm')
def confirmation_page() -> FileResponse:
    """제안 점수 확정 화면을 반환한다."""
    return FileResponse(Path(__file__).with_name('confirm.html'))


@app.get('/api/proposals')
def proposal_items() -> dict[str, Any]:
    """확인이 남은 제안과 최신 확정 및 이력을 반환한다."""
    source_hash, rows = proposal_source()
    with confirmation_db() as db:
        history = tuple({'id': key, **json.loads(payload)} for key, payload in db.execute('SELECT id, payload FROM decisions ORDER BY seq'))
    decisions = {row['id']: row for row in history if row['source_hash'] == source_hash}
    return {'source_hash': source_hash, 'items': rows, 'decisions': decisions, 'history': history}


@app.post('/api/proposals/{item_id}')
def save_proposal(item_id: str, decision: Confirmation) -> dict[str, Any]:
    """제안 확정 근거를 검증하고 기존 데이터셋은 보존하며 새 이력을 저장한다."""
    source_hash, rows = proposal_source()
    if decision.source_hash != source_hash:
        raise HTTPException(409, '제안 원본이 바뀌었습니다. 새로고침하세요')
    if item_id not in {row['id'] for row in rows}:
        raise HTTPException(404, '확정 대상이 아닙니다')
    if not decision.reason.strip():
        raise HTTPException(422, '판단 근거를 입력하세요')
    payload = {**decision.model_dump(), 'reviewer': 'human', 'updated_at': datetime.now(timezone.utc).isoformat()}
    with confirmation_db() as db:
        db.execute('INSERT INTO decisions(id,payload) VALUES (?,?)', (item_id, json.dumps(payload, ensure_ascii=False)))
    return {'id': item_id, **payload}


@app.get('/api/proposals-export')
def export_proposals() -> Response:
    """제안 원문과 확정 이력을 JSON으로 내려준다."""
    return Response(json.dumps(proposal_items(), ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition': 'attachment; filename="proposals.json"'})
