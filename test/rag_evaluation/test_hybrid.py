"""저장 run의 검증과 RRF 결합을 검증한다."""

import json
from pathlib import Path
from typing import Any

import pytest

from RAG_evaluation.retrieval.common import Inputs, Query, sha256
from RAG_evaluation.embedding.fixed_character import Document
from RAG_evaluation.retrieval.hybrid import HybridRetriever, load_run


@pytest.fixture
def inputs() -> Inputs:
    """같은 문장이지만 ID가 다른 두 쿼리와 세 공고를 준비한다."""
    docs = tuple(Document(id=f'00000000-0000-0000-0000-{i:012d}', title='제목', content='본문', url='https://example.com', metadata={}) for i in range(1, 4))
    return Inputs(docs, (Query(query_id='Q1', query='개발'), Query(query_id='Q2', query='개발')), 'a', 'b')


def write_run(path: Path, inputs: Inputs, method: str, order: tuple[int, ...]) -> None:
    """순위와 해시가 연결된 작은 검색 결과를 저장한다."""
    rows = tuple({'query_id': q.query_id, 'doc_id': str(inputs.documents[i].id), 'rank': rank, 'score': float(4-rank)}
                 for q in inputs.queries for rank, i in enumerate(order if q.query_id == 'Q1' else tuple(reversed(order)), 1))
    raw = ''.join(json.dumps(row)+'\n' for row in rows).encode()
    (path/'runs').mkdir(exist_ok=True)
    (path/'manifests').mkdir(exist_ok=True)
    (path/'runs'/f'{method}.jsonl').write_bytes(raw)
    manifest = {'schema_version': 1, 'status': 'completed', 'run_id': method, 'retrieval_method': method,
                'ranking_unit': 'document', 'tie_break': 'doc_id_ascending', 'corpus_version': 'v1',
                'corpus_sha256': 'a', 'query_sha256': 'b', 'document_count': 3, 'query_count': 2,
                'run_file': f'runs/{method}.jsonl', 'run_sha256': sha256(raw), 'top_k': 2, 'result_count': 4}
    (path/'manifests'/f'{method}.json').write_text(json.dumps(manifest))


def test_rrf_파일_순위와_쿼리_ID(tmp_path: Path, inputs: Inputs) -> None:
    """같은 문장의 쿼리도 ID로 구분하고 중복 공고의 순위를 합산한다."""
    write_run(tmp_path, inputs, 'dense', (0, 1))
    write_run(tmp_path, inputs, 'bm25', (2, 0))
    dense = load_run(tmp_path, 'dense', 'dense', inputs, 'v1')
    bm25 = load_run(tmp_path, 'bm25', 'bm25', inputs, 'v1')
    retriever = HybridRetriever(dense, bm25)
    a, b, c = (str(d.id) for d in inputs.documents)
    assert retriever.search('Q1', 2) == ((a, 1/61+1/62), (c, 1/61))
    assert retriever.search('Q2', 2) == ((a, 1/61+1/62), (b, 1/61))
    assert retriever.search('Q1', 2) == retriever.search('Q1', 2)
    assert dense.provenance()['manifest_sha256'] == sha256((tmp_path/'manifests/dense.json').read_bytes())
    with pytest.raises(ValueError):
        retriever.search('Q1', 3)
    with pytest.raises(ValueError):
        retriever.search('unknown', 2)
    with pytest.raises(ValueError):
        HybridRetriever(dense, bm25, 0)


@pytest.mark.parametrize('field,value', [('status', 'running'), ('query_sha256', 'wrong'), ('corpus_sha256', 'wrong'), ('retrieval_method', 'bm25'), ('result_count', 3), ('top_k', 0)])
def test_다른_실험과_미완료_거절(tmp_path: Path, inputs: Inputs, field: str, value: Any) -> None:
    """입력 불일치와 미완료 manifest를 융합 전에 거절한다."""
    write_run(tmp_path, inputs, 'dense', (0, 1))
    path = tmp_path/'manifests/dense.json'
    path.write_text(json.dumps({**json.loads(path.read_text()), field: value}))
    with pytest.raises(ValueError):
        load_run(tmp_path, 'dense', 'dense', inputs, 'v1')


@pytest.mark.parametrize('change', ['hash', 'duplicate', 'rank', 'query', 'doc', 'nan'])
def test_손상된_결과_거절(tmp_path: Path, inputs: Inputs, change: str) -> None:
    """해시 손상과 해시만 일치하는 잘못된 결과 행도 거절한다."""
    write_run(tmp_path, inputs, 'dense', (0, 1))
    path = tmp_path/'runs/dense.jsonl'
    rows = tuple(json.loads(line) for line in path.read_text().splitlines())
    changes = {'duplicate': {'doc_id': rows[1]['doc_id']}, 'rank': {'rank': 2},
               'query': {'query_id': 'unknown'}, 'doc': {'doc_id': 'unknown'}, 'nan': {'score': float('nan')}, 'hash': {'score': 99.0}}
    raw = '\n'.join(json.dumps(row) for row in ({**rows[0], **changes[change]}, *rows[1:])).encode()
    path.write_bytes(raw)
    if change != 'hash':
        manifest = tmp_path/'manifests/dense.json'
        manifest.write_text(json.dumps({**json.loads(manifest.read_text()), 'run_sha256': sha256(raw)}))
    with pytest.raises(ValueError):
        load_run(tmp_path, 'dense', 'dense', inputs, 'v1')
