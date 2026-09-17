"""3,022쌍 라벨을 출처 우선순위로 합쳐 pool_v1을 만든다. 기존 파일은 지우지 않는다."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / 'RAG_evaluation/artifacts/zighang_v1'
DESTINATION = ROOT / 'RAG_evaluation/dataset/labeling/pool_v1'
GUIDELINES = ROOT / 'docs/labeling-guidelines.md'
PILOT = ROOT / 'RAG_evaluation/dataset/labeling/pilot_aligned_v2/pairs.jsonl'
HOLDOUT_ITEMS = ARTIFACTS / 'labeling_holdout_v1/holdout.json'
HOLDOUT_LABELS = ARTIFACTS / 'labeling_holdout_v1/labels.sqlite3'
REMAINING = ARTIFACTS / 'labeling_first_pass_v1/remaining.jsonl'
GROK = ARTIFACTS / 'labeling_first_pass_v1/grok_v1/judgments.jsonl'
REVIEW = ARTIFACTS / 'labeling_first_pass_v1/review.sqlite3'
RUNS = (
    ARTIFACTS / 'runs/dense_fixed1000_qwen1536_v1.jsonl',
    ARTIFACTS / 'runs/bm25_kiwi_v1.jsonl',
)


def load_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    """JSONL 파일을 불변 행 목록으로 읽는다."""
    return tuple(json.loads(line) for line in path.read_text().splitlines() if line.strip())


def sqlite_labels(path: Path) -> dict[str, dict[str, Any]]:
    """라벨 sqlite의 최신 행을 읽는다."""
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
        return {key: json.loads(payload) for key, payload in db.execute('SELECT id, payload FROM labels')}


def score_of(value: Any) -> int:
    """0·1·2만 점수로 받는다."""
    if type(value) is not int or value not in (0, 1, 2):
        raise ValueError(f'잘못된 점수: {value}')
    return value


def pool_ids() -> frozenset[str]:
    """Dense·BM25 top-20 합집합 쌍 ID를 모은다."""
    return frozenset(
        f"{row['query_id']}:{row['doc_id']}"
        for path in RUNS for row in load_jsonl(path)
    )


def layer_pilot() -> dict[str, dict[str, Any]]:
    """파일럿 확정 120건을 읽는다."""
    return {
        row['pair_id']: {
            'query_id': row['query_id'], 'doc_id': row['doc_id'], 'query': row['query'],
            'score': score_of(row['score']), 'source': 'human_pilot',
        }
        for row in load_jsonl(PILOT)
    }


def layer_holdout() -> dict[str, dict[str, Any]]:
    """holdout 사람 120건을 읽는다."""
    items = {item['id']: item for item in json.loads(HOLDOUT_ITEMS.read_text())['items']}
    labels = sqlite_labels(HOLDOUT_LABELS)
    if set(labels) != set(items):
        raise ValueError('holdout 라벨과 표본 ID가 다릅니다')
    return {
        key: {
            'query_id': items[key]['query_id'], 'doc_id': items[key]['doc_id'],
            'query': items[key]['query'], 'score': score_of(row['label']),
            'source': 'human_holdout',
        }
        for key, row in labels.items()
    }


def layer_review() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """1차 검수의 사람 129건과 에이전트 224건을 나눈다."""
    remaining = {row['id']: row for row in load_jsonl(REMAINING)}
    human: dict[str, dict[str, Any]] = {}
    assistant: dict[str, dict[str, Any]] = {}
    for key, row in sqlite_labels(REVIEW).items():
        item = remaining[key]
        payload = {
            'query_id': item['query_id'], 'doc_id': item['doc_id'], 'query': item['query'],
            'score': score_of(row['label']),
            'source': 'human_review' if row.get('reviewer') == 'human' else 'assistant_review',
        }
        if row.get('reviewer') == 'human':
            human = {**human, key: payload}
        else:
            assistant = {**assistant, key: payload}
    return human, assistant


def layer_grok() -> dict[str, dict[str, Any]]:
    """Grok 1차 중 검수 표시가 없는 자동 통과분이다."""
    remaining = {row['id']: row for row in load_jsonl(REMAINING)}
    return {
        row['id']: {
            'query_id': remaining[row['id']]['query_id'],
            'doc_id': remaining[row['id']]['doc_id'],
            'query': remaining[row['id']]['query'],
            'score': score_of(row['label']),
            'source': 'grok_first_pass',
        }
        for row in load_jsonl(GROK)
        if not row.get('review') and row['id'] in remaining
    }


def assemble() -> tuple[dict[str, Any], ...]:
    """우선순위대로 합친다. 사람 점수가 에이전트보다 앞선다."""
    human, assistant = layer_review()
    merged: dict[str, dict[str, Any]] = {}
    for layer in (layer_grok(), assistant, human, layer_holdout(), layer_pilot()):
        merged = {**merged, **layer}
    pool = pool_ids()
    if set(merged) != pool:
        raise ValueError(f'합친 ID가 pool과 다릅니다: {len(merged)} vs {len(pool)}')
    rows = tuple(
        {
            'pair_id': key,
            'query_id': row['query_id'],
            'doc_id': row['doc_id'],
            'query': row['query'],
            'score': row['score'],
            'source': row['source'],
            'dataset_version': 'pool_v1',
            'guideline_version': '1.4',
            'reference_date': '2026-09-07',
        }
        for key, row in sorted(merged.items())
    )
    return rows


def main() -> None:
    """pool_v1을 저장하고 기존 산출물은 그대로 둔다."""
    rows = assemble()
    counts = dict(Counter(row['source'] for row in rows))
    scores = dict(Counter(str(row['score']) for row in rows))
    assert counts == {
        'human_pilot': 120, 'human_holdout': 120, 'human_review': 129,
        'assistant_review': 224, 'grok_first_pass': 2429,
    }
    text = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows)
    qrels = ''.join(f"{row['query_id']} 0 {row['doc_id']} {row['score']}\n" for row in rows)
    sources = (PILOT, HOLDOUT_ITEMS, HOLDOUT_LABELS, REMAINING, GROK, REVIEW, GUIDELINES, *RUNS)
    manifest = {
        'dataset_version': 'pool_v1',
        'count': len(rows),
        'score_scale': [0, 1, 2],
        'score_counts': scores,
        'source_counts': counts,
        'all_human_confirmed': False,
        'audit_50_applied': False,
        'note': '감사 50건은 화면 확인만 하고 버튼 저장을 하지 않아 반영하지 않았다. 기존 artifacts와 파일럿 파일은 삭제하지 않았다.',
        'source_hashes': {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources
        },
        'data_sha256': hashlib.sha256(text.encode()).hexdigest(),
    }
    DESTINATION.mkdir(parents=True, exist_ok=True)
    outputs = {
        'judgments.jsonl': text,
        'qrels.txt': qrels,
        'manifest.json': json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
    }
    for name, content in outputs.items():
        target = DESTINATION / name
        if target.exists() and target.read_text() != content:
            raise ValueError(f'기존 버전 덮어쓰기 금지: {target}')
    for name, content in outputs.items():
        (DESTINATION / name).write_text(content)
    print(json.dumps({'count': len(rows), 'sources': counts, 'scores': scores, 'path': str(DESTINATION)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
