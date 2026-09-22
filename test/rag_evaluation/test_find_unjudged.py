"""미평가 쌍 추출과 불완전한 라벨링 자료의 저장 방지를 검증한다."""

import json
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from RAG_evaluation.labeling import find_unjudged as module

DOC = '9b46bffb-8536-475c-9196-ba87ac33d5b6'


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """독립된 corpus·쿼리·pool과 검색 결과를 구성한다."""
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module, 'DATASET', tmp_path / 'dataset')
    monkeypatch.setattr(module, 'ARTIFACTS', tmp_path / 'artifacts')
    monkeypatch.setattr(module, 'GUIDELINES', tmp_path / 'guidelines.md')
    files = {
        'guidelines.md': '버전 1.4 · 평가 시간 기준 2026-09-07',
        'dataset/labeling/pool_v1/qrels.txt': 'Q001 0 existing 0\n',
        'dataset/queries/eval_queries_80.jsonl': json.dumps({'query_id': 'Q001', 'query': '백엔드'}),
        'dataset/corpus.jsonl': json.dumps({
            'id': DOC, 'title': '백엔드 개발', 'content': 'Python 개발 업무',
            'url': 'https://example.com', 'metadata': {'company': 'example'},
        }),
        'artifacts/runs/run.jsonl': json.dumps({
            'query_id': 'Q001',
            'candidates': [{'doc_id': DOC, 'rank': 1, 'score': 0.9}],
            'ranked': [{'doc_id': DOC, 'rank': 1, 'score': 0.9}],
            'recommended': [{'doc_id': DOC}],
        }),
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    return tmp_path


def test_extract_deduplicates_and_preserves_outputs(workspace: Path) -> None:
    """단계 간 중복 쌍을 합치고 순위·점수 없이 원문을 보존한다."""
    first = module.find_unjudged('run.jsonl', 'pool_v1')
    assert first is not None
    original = (first / 'pairs.jsonl').read_bytes()
    rows = [json.loads(line) for line in original.splitlines()]
    assert len(rows) == 1
    assert rows[0]['pair_id'] == f'Q001:{DOC}'
    assert rows[0]['document']['metadata'] == {'company': 'example'}
    assert 'score' not in rows[0] and 'rank' not in rows[0]
    manifest = json.loads((first / 'manifest.json').read_text())
    assert manifest['reference_date'] == '2026-09-07'
    assert len(manifest['source_hashes']) == 5
    second = module.find_unjudged('run.jsonl', 'pool_v1')
    assert second != first
    assert (first / 'pairs.jsonl').read_bytes() == original


def test_no_missing_creates_nothing(workspace: Path) -> None:
    """0점 라벨도 기존 판정으로 인정하고 신규가 없으면 저장하지 않는다."""
    (module.DATASET / 'labeling/pool_v1/qrels.txt').write_text(f'Q001 0 {DOC} 0\n')
    assert module.find_unjudged('run.jsonl', 'pool_v1') is None
    assert not (module.ARTIFACTS / 'labeling_pending').exists()


def test_missing_source_does_not_write(workspace: Path) -> None:
    """원문에 없는 ID를 안내하고 출력물을 만들지 않는다."""
    path = module.DATASET / 'queries/eval_queries_80.jsonl'
    path.write_text(json.dumps({'query_id': 'Q002', 'query': '다른 질문'}))
    with pytest.raises(ValueError, match=f'Q001:{DOC}'):
        module.find_unjudged('run.jsonl', 'pool_v1')
    assert not (module.ARTIFACTS / 'labeling_pending').exists()


@pytest.mark.parametrize(('filename', 'pool'), [('../run.jsonl', 'pool_v1'), ('run.jsonl', '../pool_v1')])
def test_reject_path_traversal(filename: str, pool: str) -> None:
    """파일명과 pool 버전에 경로 입력을 허용하지 않는다."""
    with pytest.raises(ValueError):
        module.find_unjudged(filename, pool)
