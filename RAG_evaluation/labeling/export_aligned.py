"""파일럿 원문·최초 판정·후속 합의를 하나의 버전 데이터셋으로 묶는다."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'RAG_evaluation/artifacts/zighang_v1/labeling_pilot_v1'
DESTINATION = ROOT / 'RAG_evaluation/dataset/labeling/pilot_aligned_v1'

# 사용자가 대화에서 직접 확정한 후속 5건이다.
CONFIRMED = {
    'Q067:a334f76d-81e1-45ed-a7d8-6ad485f53ac6': (2, '채용 관점의 대기업·대형 테크 범주로 코웨이 공고를 관련으로 확정'),
    'Q067:65c505a5-72f4-4f65-9b48-872a03c13cb6': (0, '대기업 고객의 프로젝트 수행은 대기업 직접 채용을 뜻하지 않음'),
    'Q047:2a8ad408-1ed9-44e9-813c-2517c8d8edcd': (2, '경력 8년 이상은 8년차가 지원 가능한 공고로 해석하며 사용자가 2점 확정'),
    'Q042:f2fff974-588f-4047-830e-31dfa7570ca7': (1, '교대근무를 확정할 근거가 부족하여 부분 관련'),
    'Q011:2c42ac8b-95ce-4242-9641-97df9a466772': (2, '백엔드 아키텍처 설계·구현이 핵심인 역할도 백엔드 채용에 포함'),
}


def load_json(path: Path) -> Any:
    """UTF-8 JSON 자료를 읽는다."""
    return json.loads(path.read_text())


def main() -> None:
    """ID·출처·상태를 검증하고 0·1·2점 세트를 내보낸다."""
    pilot = load_json(SOURCE / 'pilot.json')
    comparison_path = SOURCE / 'llm_blind_v1/agent_comparison.json'
    comparison = load_json(comparison_path)
    original = {row['id']: row for row in comparison['rows']}
    source_hash = hashlib.sha256(comparison_path.read_bytes()).hexdigest()
    with sqlite3.connect(f'file:{SOURCE / "alignment.sqlite3"}?mode=ro', uri=True) as db:
        history = tuple({'id': key, **json.loads(payload)} for key, payload in db.execute('SELECT id,payload FROM decisions ORDER BY seq'))
    aligned = {row['id']: row for row in history if row['source_hash'] == source_hash}
    # 문서의 17건 제안 표만 읽는다. 이 값들을 사용자 확정으로 승격하지 않는다.
    report = (SOURCE / 'remaining22_review.md').read_text()
    section = report.split('## 기준으로 점수를 제안한 17건')[1].split('## 사용자 판단')[0]
    proposals = tuple(tuple(cell.strip() for cell in line.split('|')[1:-1])
                      for line in section.splitlines() if line.startswith('| Q'))
    assert len(proposals) == 17
    proposed = {}
    for query_id, _, _, label, reason in proposals:
        matches = tuple(row for row in original.values() if row['id'].startswith(query_id + ':') and row['human'] != row['agent'])
        assert len(matches) == 1, f'제안 ID 연결 실패: {query_id}'
        proposed = {**proposed, matches[0]['id']: (int(label), reason)}
    assert len(aligned) == 5 and set(aligned).isdisjoint(CONFIRMED)
    assert set(proposed).isdisjoint(set(aligned) | set(CONFIRMED))
    assert set(proposed) | set(aligned) | set(CONFIRMED) == {key for key, row in original.items() if row['human'] != row['agent']}

    def assemble(item: dict[str, Any]) -> dict[str, Any]:
        """한 후보에 최초 판정과 최신 판정 상태를 연결한다."""
        key = item['id']
        old = original[key]
        if key in CONFIRMED:
            label, reason = CONFIRMED[key]
            status, provenance = 'human_confirmed', 'conversation_2026-09-15'
        elif key in aligned:
            label, reason = aligned[key]['label'], aligned[key]['reason']
            status, provenance = 'human_confirmed', 'alignment.sqlite3'
        elif key in proposed:
            label, reason = proposed[key]
            status, provenance = 'assistant_proposed', 'remaining22_review.md'
        else:
            label, reason = old['human'], old['human_note'] or '최초 사람·독립 에이전트 점수 일치'
            status, provenance = 'original_agreement', 'agent_comparison.json'
        assert type(label) is int and label in (0, 1, 2)
        return {'schema_version': 1, 'dataset_version': 'pilot_aligned_v1', 'pair_id': key,
                'query_id': item['query_id'], 'query': item['query'], 'query_type': item['type'],
                'doc_id': item['doc_id'], 'document': item['document'],
                'score': label, 'status': status, 'reason': reason,
                'provenance': provenance, 'initial_human_relevance': old['human'],
                'initial_human_note': old['human_note'], 'initial_agent_relevance': old['agent'],
                'initial_agent_reason': old['reason'], 'initial_agent_review': old['review'],
                'reference_date': '2026-09-07', 'guideline_version': '1.0',
                'requires_confirmation': status == 'assistant_proposed'}

    rows = tuple(assemble(item) for item in pilot['items'])
    assert len(rows) == len({row['pair_id'] for row in rows}) == 120
    counts = dict(Counter(row['status'] for row in rows))
    assert counts == {'original_agreement': 93, 'human_confirmed': 10, 'assistant_proposed': 17}
    text = '\n'.join(json.dumps(row, ensure_ascii=False) for row in rows) + '\n'
    sources = (SOURCE / 'pilot.json', comparison_path, SOURCE / 'remaining22_review.md', ROOT / 'docs/labeling-guidelines.md')
    manifest = {'dataset_version': 'pilot_aligned_v1', 'count': len(rows), 'status_counts': counts,
                'score_scale': [0, 1, 2],
                'score_counts': dict(Counter(str(row['score']) for row in rows)),
                'all_human_confirmed': False,
                'source_hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                'alignment_history_sha256': hashlib.sha256(json.dumps(history, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                'data_sha256': hashlib.sha256(text.encode()).hexdigest()}
    DESTINATION.mkdir(parents=True, exist_ok=True)
    outputs = {'pairs.jsonl': text, 'manifest.json': json.dumps(manifest, ensure_ascii=False, indent=2) + '\n'}
    for name, content in outputs.items():
        target = DESTINATION / name
        if target.exists() and target.read_text() != content:
            raise ValueError(f'기존 버전 덮어쓰기 금지: {target}')
    for name, content in outputs.items():
        (DESTINATION / name).write_text(content)
    print(json.dumps({'count': len(rows), 'statuses': counts, 'score_counts': manifest['score_counts']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
