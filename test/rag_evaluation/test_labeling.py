"""사용자 판정 저장과 파일럿 구성 회귀 검증."""
from collections import Counter
import json
from pathlib import Path
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from RAG_evaluation.labeling import app as module


def test_audit_sample_is_balanced_and_disjoint() -> None:
    """자동 통과 감사 50건은 0/2와 유형이 섞이고 검수 353과 겹치지 않는다."""
    assert len(module.AUDIT_ITEMS) == len({item['id'] for item in module.AUDIT_ITEMS}) == 50
    assert Counter(item['grok_label'] for item in module.AUDIT_ITEMS) == {0: 25, 2: 25}
    assert set(item['type'] for item in module.AUDIT_ITEMS) == {
        'ambiguous', 'constraint-heavy', 'entity-heavy', 'keyword', 'no-match', 'semantic',
    }
    assert {item['id'] for item in module.AUDIT_ITEMS}.isdisjoint({item['id'] for item in module.REVIEW_ITEMS})


def test_review_save_preserves_grok_judgments(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """1차 검수는 별도 DB에 저장하고 Grok 판정 파일은 바꾸지 않는다."""
    remaining = tmp_path / 'remaining.jsonl'
    grok = tmp_path / 'grok_v1'
    grok.mkdir()
    item = {
        'id': 'Q099:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'query_id': 'Q099',
        'query': '테스트', 'type': 'keyword', 'intent': '', 'interpretations': [],
        'warning': '', 'doc_id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        'document': {'title': '공고', 'content': '본문', 'metadata': {'company': '테스트'}},
    }
    remaining.write_text(json.dumps(item, ensure_ascii=False) + '\n')
    judgments = grok / 'judgments.jsonl'
    original = json.dumps({'id': item['id'], 'label': 1, 'reason': '부분', 'review': True,
                           'flags': ['partial_duty'], 'confidence': 'high'}, ensure_ascii=False) + '\n'
    judgments.write_text(original)
    monkeypatch.setattr(module, 'FIRST_PASS', tmp_path)
    monkeypatch.setattr(module, 'REVIEW_ITEMS', module.prepare_review())
    client = TestClient(module.app)
    data = client.get('/api/review/items').json()
    assert [row['id'] for row in data['items']] == [item['id']]
    assert data['items'][0]['grok_label'] == 1
    assert client.post('/api/review/labels/' + item['id'], json={'label': 0, 'note': '직무 다름'}).status_code == 200
    resumed = TestClient(module.app).get('/api/review/items').json()['labels']
    assert resumed[item['id']]['label'] == 0
    assert judgments.read_text() == original
    assert client.post('/api/review/labels/' + module.ITEMS[0]['id'], json={'label': 2}).status_code == 404


def test_holdout_alignment_preserves_human_labels(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """holdout 0↔2 합의 이력은 사람 라벨 DB를 바꾸지 않는다."""
    first = module.HOLDOUT_ITEMS[0]
    monkeypatch.setattr(module, 'HOLDOUT_OUTPUT', tmp_path)
    folder = tmp_path / 'llm_blind_v1'
    folder.mkdir()
    source = folder / 'agent_comparison.json'
    source.write_text(json.dumps({'rows': [{'id': first['id'], 'query': first['query'], 'title': first['document']['title'],
                                            'human': 2, 'agent': 0, 'human_note': '', 'reason': '에이전트',
                                            'evidence': ['근거'], 'review': False}]}))
    labels = tmp_path / 'labels.sqlite3'
    labels.write_bytes(b'preserve-holdout-labels')
    original = source.read_bytes()
    client = TestClient(module.app)
    data = client.get('/api/holdout-alignment').json()
    assert [row['id'] for row in data['items']] == [first['id']]
    payload = {'label': 0, 'rule': '핵심 직무가 다름', 'reason': '인턴은 시니어 역할이 아님', 'source_hash': data['source_hash']}
    endpoint = '/api/holdout-alignment/' + first['id']
    assert client.post(endpoint, json=payload).status_code == 200
    assert client.post(endpoint, json={**payload, 'label': 'review'}).status_code == 200
    resumed = TestClient(module.app).get('/api/holdout-alignment-export').json()
    assert len(resumed['history']) == 2
    assert resumed['decisions'][first['id']]['label'] == 'review'
    assert labels.read_bytes() == b'preserve-holdout-labels'
    assert source.read_bytes() == original
    assert client.post(endpoint, json={**payload, 'reason': ' '}).status_code == 422
    assert client.post(endpoint, json={**payload, 'source_hash': 'stale'}).status_code == 409
    assert client.post('/api/holdout-alignment/unknown', json=payload).status_code == 404


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


def test_pilot_aligned_v2_is_fully_confirmed() -> None:
    """v2는 120건 전원 확정이고 제안에서 바뀐 3건만 점수가 다르다."""
    root = Path(__file__).resolve().parents[2]
    previous = tuple(json.loads(line) for line in (root / 'RAG_evaluation/dataset/labeling/pilot_aligned_v1/pairs.jsonl').read_text().splitlines() if line.strip())
    current = tuple(json.loads(line) for line in (root / 'RAG_evaluation/dataset/labeling/pilot_aligned_v2/pairs.jsonl').read_text().splitlines() if line.strip())
    manifest = json.loads((root / 'RAG_evaluation/dataset/labeling/pilot_aligned_v2/manifest.json').read_text())
    assert len(current) == len({row['pair_id'] for row in current}) == 120
    assert all(not row['requires_confirmation'] for row in current)
    assert Counter(row['status'] for row in current) == {'original_agreement': 93, 'human_confirmed': 27}
    assert Counter(str(row['score']) for row in current) == {'0': 78, '1': 10, '2': 32}
    assert manifest['all_human_confirmed'] is True
    changed = {old['pair_id']: (old['score'], row['score']) for old, row in zip(previous, current) if old['score'] != row['score']}
    assert changed == {
        'Q040:d72a9bdb-28b1-4232-9f03-1ba3313ed642': (1, 2),
        'Q027:8aef8e4e-6d8a-4218-a6bb-4846cdfc88ae': (1, 2),
        'Q023:91c44605-606c-446a-9fa1-06534dd93c19': (0, 1),
    }


def test_sample() -> None:
    """유형 균형과 모든 쿼리 포함 여부를 검증한다."""
    assert len(module.ITEMS) == 120
    assert len({i['id'] for i in module.ITEMS}) == 120
    assert set(Counter(i['type'] for i in module.ITEMS).values()) == {20}
    assert len({i['query_id'] for i in module.ITEMS}) == 80


def test_holdout_sample_is_disjoint() -> None:
    """holdout은 120쌍이고 파일럿과 겹치지 않는다."""
    assert len(module.HOLDOUT_ITEMS) == 120
    assert len({i['id'] for i in module.HOLDOUT_ITEMS}) == 120
    assert set(Counter(i['type'] for i in module.HOLDOUT_ITEMS).values()) == {20}
    assert len({i['query_id'] for i in module.HOLDOUT_ITEMS}) == 80
    assert {i['id'] for i in module.HOLDOUT_ITEMS}.isdisjoint({i['id'] for i in module.ITEMS})


def test_holdout_save_resume_export(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """holdout 판정이 파일럿 저장소와 분리되고 재개·내보내기가 된다."""
    monkeypatch.setattr(module, 'HOLDOUT_OUTPUT', tmp_path / 'holdout')
    monkeypatch.setattr(module, 'OUTPUT', tmp_path / 'pilot')
    client = TestClient(module.app)
    first, second = module.HOLDOUT_ITEMS[:2]
    assert client.post('/api/holdout/labels/'+first['id'], json={'label':2,'note':'검증'}).status_code == 200
    assert client.post('/api/holdout/labels/'+first['id'], json={'label':1,'note':'수정'}).status_code == 200
    assert client.post('/api/holdout/labels/'+second['id'], json={'label':'review'}).status_code == 200
    resumed = TestClient(module.app).get('/api/holdout/items').json()['labels']
    assert resumed[first['id']]['note'] == '수정'
    assert resumed[first['id']]['label'] == 1
    export = client.get('/api/holdout/export/json').json()
    assert export['unjudged'] == 118
    assert export['counts'] == {'1':1,'review':1}
    assert client.get('/api/holdout/export/qrels').text.strip() == f"{first['query_id']} 0 {first['doc_id']} 1"
    assert client.post('/api/holdout/labels/'+module.ITEMS[0]['id'], json={'label':0}).status_code == 404
    assert not (tmp_path / 'pilot' / 'labels.sqlite3').exists()


def test_proposal_confirmation_preserves_aligned_dataset(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """제안 확정 이력·재접속·원본 보존·잘못된 입력 차단을 검증한다."""
    monkeypatch.setattr(module, 'OUTPUT', tmp_path)
    monkeypatch.setattr(module, 'ALIGNED', tmp_path)
    pair = {
        'pair_id': 'Q099:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'query_id': 'Q099',
        'query': '테스트 질의', 'query_type': 'keyword',
        'doc_id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        'document': {'title': '테스트 공고', 'content': '본문',
                     'metadata': {'company': {'name': '테스트'}, 'regions': ['서울'],
                                  'careerMin': 0, 'careerMax': 100, 'endDate': ''}},
        'score': 1, 'status': 'assistant_proposed', 'reason': '제안 이유',
        'initial_human_relevance': 2, 'initial_human_note': '사람 메모',
        'initial_agent_relevance': 0, 'initial_agent_reason': '에이전트 이유',
        'requires_confirmation': True,
    }
    ignored = {**pair, 'pair_id': 'Q100:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
               'requires_confirmation': False, 'status': 'original_agreement'}
    source = tmp_path / 'pairs.jsonl'
    source.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in (ignored, pair)) + '\n')
    labels = tmp_path / 'labels.sqlite3'
    labels.write_bytes(b'preserve-labels')
    original = source.read_bytes()
    client = TestClient(module.app)
    data = client.get('/api/proposals').json()
    assert [row['id'] for row in data['items']] == [pair['pair_id']]
    payload = {'label': 0, 'reason': '핵심 직무가 다름', 'source_hash': data['source_hash']}
    endpoint = '/api/proposals/' + pair['pair_id']
    assert client.post(endpoint, json=payload).status_code == 200
    assert client.post(endpoint, json={**payload, 'label': 'review'}).status_code == 200
    resumed = TestClient(module.app).get('/api/proposals-export').json()
    assert len(resumed['history']) == 2
    assert resumed['decisions'][pair['pair_id']]['label'] == 'review'
    assert source.read_bytes() == original
    assert labels.read_bytes() == b'preserve-labels'
    assert client.post(endpoint, json={**payload, 'reason': ' '}).status_code == 422
    assert client.post(endpoint, json={**payload, 'source_hash': 'stale'}).status_code == 409
    assert client.post('/api/proposals/unknown', json=payload).status_code == 404


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
