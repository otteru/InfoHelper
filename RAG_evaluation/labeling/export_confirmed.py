"""확인된 17건을 반영한 파일럿 데이터셋 v2를 만든다."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'RAG_evaluation/artifacts/zighang_v1/labeling_pilot_v1'
PREVIOUS = ROOT / 'RAG_evaluation/dataset/labeling/pilot_aligned_v1'
DESTINATION = ROOT / 'RAG_evaluation/dataset/labeling/pilot_aligned_v2'
GUIDELINES = ROOT / 'docs/labeling-guidelines.md'


def load_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    """JSONL 파일을 불변 행 목록으로 읽는다."""
    return tuple(json.loads(line) for line in path.read_text().splitlines() if line.strip())


def latest_confirmations(path: Path, source_hash: str) -> dict[str, dict[str, Any]]:
    """제안 원본 해시에 해당하는 최신 확정만 남긴다."""
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
        history = tuple(
            {'id': key, **json.loads(payload)}
            for key, payload in db.execute('SELECT id, payload FROM decisions ORDER BY seq')
        )
    latest: dict[str, dict[str, Any]] = {}
    for row in history:
        if row['source_hash'] == source_hash:
            latest = {**latest, row['id']: row}
    return latest


def assemble(row: dict[str, Any], confirmed: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """v1 행에 사용자 확정이 있으면 점수와 출처만 갱신한다."""
    decision = confirmed.get(row['pair_id'])
    if decision is None:
        return {
            **row,
            'dataset_version': 'pilot_aligned_v2',
            'guideline_version': '1.1',
        }
    label = decision['label']
    assert type(label) is int and label in (0, 1, 2)
    return {
        **row,
        'dataset_version': 'pilot_aligned_v2',
        'score': label,
        'status': 'human_confirmed',
        'reason': decision['reason'],
        'provenance': 'confirmation.sqlite3',
        'guideline_version': '1.1',
        'requires_confirmation': False,
    }


def main() -> None:
    """17건 확정을 검증하고 v1을 덮어쓰지 않은 v2를 저장한다."""
    previous_text = (PREVIOUS / 'pairs.jsonl').read_text()
    source_hash = hashlib.sha256(previous_text.encode()).hexdigest()
    manifest = json.loads((PREVIOUS / 'manifest.json').read_text())
    assert source_hash == manifest['data_sha256']
    confirmed = latest_confirmations(SOURCE / 'confirmation.sqlite3', source_hash)
    previous = load_jsonl(PREVIOUS / 'pairs.jsonl')
    proposed = {row['pair_id'] for row in previous if row['requires_confirmation']}
    assert proposed == set(confirmed)
    assert len(confirmed) == 17
    assert all(row['label'] in (0, 1, 2) for row in confirmed.values())

    rows = tuple(assemble(row, confirmed) for row in previous)
    assert len(rows) == 120
    assert {row['pair_id'] for row in rows} == {row['pair_id'] for row in previous}
    assert all(not row['requires_confirmation'] for row in rows)
    counts = dict(Counter(row['status'] for row in rows))
    assert counts == {'original_agreement': 93, 'human_confirmed': 27}
    text = '\n'.join(json.dumps(row, ensure_ascii=False) for row in rows) + '\n'
    qrels = '\n'.join(f"{row['query_id']} 0 {row['doc_id']} {row['score']}" for row in rows) + '\n'
    history = json.dumps(tuple(confirmed[key] for key in sorted(confirmed)), ensure_ascii=False, sort_keys=True)
    sources = (PREVIOUS / 'pairs.jsonl', SOURCE / 'confirmation.sqlite3', GUIDELINES)
    output_manifest = {
        'dataset_version': 'pilot_aligned_v2',
        'count': len(rows),
        'status_counts': counts,
        'score_scale': [0, 1, 2],
        'score_counts': dict(Counter(str(row['score']) for row in rows)),
        'all_human_confirmed': True,
        'changed_from_proposal': {
            row['pair_id']: {'from': old['score'], 'to': row['score']}
            for old, row in zip(previous, rows) if old['requires_confirmation'] and old['score'] != row['score']
        },
        'source_hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        'confirmation_history_sha256': hashlib.sha256(history.encode()).hexdigest(),
        'previous_data_sha256': source_hash,
        'data_sha256': hashlib.sha256(text.encode()).hexdigest(),
    }
    assert output_manifest['score_counts'] == {'0': 78, '1': 10, '2': 32}
    assert output_manifest['changed_from_proposal'] == {
        'Q040:d72a9bdb-28b1-4232-9f03-1ba3313ed642': {'from': 1, 'to': 2},
        'Q027:8aef8e4e-6d8a-4218-a6bb-4846cdfc88ae': {'from': 1, 'to': 2},
        'Q023:91c44605-606c-446a-9fa1-06534dd93c19': {'from': 0, 'to': 1},
    }
    DESTINATION.mkdir(parents=True, exist_ok=True)
    outputs = {
        'pairs.jsonl': text,
        'qrels.txt': qrels,
        'manifest.json': json.dumps(output_manifest, ensure_ascii=False, indent=2) + '\n',
    }
    for name, content in outputs.items():
        target = DESTINATION / name
        if target.exists() and target.read_text() != content:
            raise ValueError(f'기존 버전 덮어쓰기 금지: {target}')
    for name, content in outputs.items():
        (DESTINATION / name).write_text(content)
    print(json.dumps({
        'count': len(rows),
        'statuses': counts,
        'score_counts': output_manifest['score_counts'],
        'changed': output_manifest['changed_from_proposal'],
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
