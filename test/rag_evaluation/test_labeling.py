"""사용자 판정 저장과 파일럿 구성 회귀 검증."""
from collections import Counter
import json
from pathlib import Path
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from RAG_evaluation.labeling import app as module


def test_alignment_history_and_original_preservation(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """합의 수정 이력·재접속·원본 보존·잘못된 입력 차단을 검증한다."""
    first = module.ITEMS[0]
    monkeypatch.setattr(module, 'OUTPUT', tmp_path)
    folder = tmp_path / 'llm_blind_v1'
    folder.mkdir()
    source = folder / 'agent_comparison.json'
    source.write_text(json.dumps({'rows': [{'id': first['id'], 'human': 0, 'agent': 2}]}))
    client = TestClient(module.app)
    assert client.post('/api/labels/' + first['id'], json={'label': 0}).status_code == 200
    original = (tmp_path / 'labels.sqlite3').read_bytes()
    comparison = source.read_bytes()
    data = client.get('/api/alignment').json()
    payload = {'label': 1, 'rule': '보조 업무는 부분 관련', 'reason': '주요 업무가 다름', 'source_hash': data['source_hash']}
    endpoint = '/api/alignment/' + first['id']
    assert client.post(endpoint, json=payload).status_code == 200
    assert client.post(endpoint, json={**payload, 'label': 'review'}).status_code == 200
    resumed = TestClient(module.app).get('/api/alignment-export').json()
    assert len(resumed['history']) == 2
    assert resumed['decisions'][first['id']]['label'] == 'review'
    assert (tmp_path / 'labels.sqlite3').read_bytes() == original
    assert source.read_bytes() == comparison
    assert client.post(endpoint, json={**payload, 'reason': ' '}).status_code == 422
    assert client.post(endpoint, json={**payload, 'source_hash': 'stale'}).status_code == 409
    assert client.post('/api/alignment/unknown', json=payload).status_code == 404


def test_sample() -> None:
    """유형 균형과 모든 쿼리 포함 여부를 검증한다."""
    assert len(module.ITEMS) == 120
    assert len({i['id'] for i in module.ITEMS}) == 120
    assert set(Counter(i['type'] for i in module.ITEMS).values()) == {20}
    assert len({i['query_id'] for i in module.ITEMS}) == 80


def test_save_resume_export(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """판정 수정·재접속 복원·보류 제외와 잘못된 입력 차단을 검증한다."""
    monkeypatch.setattr(module, 'OUTPUT', tmp_path)
    client = TestClient(module.app)
    first, second = module.ITEMS[:2]
    assert client.post('/api/labels/'+first['id'], json={'label':2,'note':'검증'}).status_code == 200
    assert client.post('/api/labels/'+first['id'], json={'label':1,'note':'수정'}).status_code == 200
    assert client.post('/api/labels/'+second['id'], json={'label':'review'}).status_code == 200
    resumed = TestClient(module.app).get('/api/items').json()['labels']
    assert resumed[first['id']]['note'] == '수정'
    assert resumed[first['id']]['label'] == 1
    export = client.get('/api/export/json').json()
    assert export['unjudged'] == 118
    assert export['counts'] == {'1':1,'review':1}
    assert client.get('/api/export/qrels').text.strip() == f"{first['query_id']} 0 {first['doc_id']} 1"
    assert client.post('/api/labels/nope',json={'label':0}).status_code == 404
    assert client.post('/api/labels/'+first['id'],json={'label':3}).status_code == 422
    assert client.post('/api/labels/'+first['id'],json={'label':0},headers={'Origin':'https://example.com'}).status_code == 403
