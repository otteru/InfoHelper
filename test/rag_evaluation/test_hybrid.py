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


def write_run(
    path: Path, inputs: Inputs, method: str, order: tuple[int, ...],
    *, totals: tuple[float | None, ...] = (100.0, 30.0), usd: float = 0.0,
) -> None:
    """예측 파일과 해시가 연결된 작은 검색 결과를 저장한다."""
    items = []
    for query, total in zip(inputs.queries, totals, strict=True):
        seq = order if query.query_id == 'Q1' else tuple(reversed(order))
        candidates = [{'doc_id': str(inputs.documents[i].id), 'rank': rank, 'score': float(4 - rank)}
                      for rank, i in enumerate(seq, 1)]
        items.append({
            'query_id': query.query_id, 'candidates': candidates, 'ranked': candidates,
            'timing': {'kind': 'measured', 'total_ms': total}, 'cost': {'usd': usd},
        })
    raw = ('\n'.join(json.dumps(item) for item in items) + '\n').encode()
    (path / 'runs').mkdir(exist_ok=True)
    (path / 'manifests').mkdir(exist_ok=True)
    (path / 'runs' / f'{method}.jsonl').write_bytes(raw)
    manifest = {
        'schema_version': 1, 'status': 'completed', 'run_id': method, 'retrieval_method': method,
        'ranking_unit': 'document', 'tie_break': 'doc_id_ascending', 'corpus_version': 'v1',
        'corpus_sha256': 'a', 'query_sha256': 'b', 'document_count': 3, 'query_count': 2,
        'prediction_file': f'runs/{method}.jsonl', 'prediction_sha256': sha256(raw),
        'prediction_count': len(items), 'top_k': 2, 'result_count': 4,
    }
    (path / 'manifests' / f'{method}.json').write_text(json.dumps(manifest))


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
    """해시 손상과 해시만 일치하는 잘못된 예측도 거절한다."""
    write_run(tmp_path, inputs, 'dense', (0, 1))
    path = tmp_path / 'runs/dense.jsonl'
    predictions = tuple(json.loads(line) for line in path.read_text().splitlines())
    first, second = predictions[0], predictions[0]['candidates']
    updated = {
        'duplicate': {**first, 'candidates': (second[0], {**second[1], 'doc_id': second[0]['doc_id']})},
        'rank': {**first, 'candidates': (second[0], {**second[1], 'rank': 1}),
                 'ranked': (second[0], {**second[1], 'rank': 1})},
        'query': {**first, 'query_id': 'unknown'},
        'doc': {**first, 'candidates': (second[0], {**second[1], 'doc_id': 'unknown'}),
                'ranked': (second[0], {**second[1], 'doc_id': 'unknown'})},
        'nan': {**first, 'candidates': (second[0], {**second[1], 'score': float('nan')}),
                'ranked': (second[0], {**second[1], 'score': float('nan')})},
        'hash': {**first, 'candidates': (second[0], {**second[1], 'score': 99.0}),
                 'ranked': (second[0], {**second[1], 'score': 99.0})},
    }[change]
    raw = ('\n'.join(json.dumps(item) for item in (updated, predictions[1])) + '\n').encode()
    path.write_bytes(raw)
    if change != 'hash':
        manifest = tmp_path / 'manifests/dense.json'
        manifest.write_text(json.dumps({**json.loads(manifest.read_text()), 'prediction_sha256': sha256(raw)}))
    with pytest.raises(ValueError):
        load_run(tmp_path, 'dense', 'dense', inputs, 'v1')


def test_쿼리별_병렬_추정과_저장(tmp_path: Path, inputs: Inputs) -> None:
    """서로 다른 검색기가 느린 쿼리별로 max를 계산하고 계측값을 저장한다."""
    import argparse
    from unittest.mock import patch
    from RAG_evaluation.retrieval import hybrid
    from RAG_evaluation.retrieval.common import save_results
    from RAG_evaluation.benchmark.loader import load_predictions

    write_run(tmp_path, inputs, 'dense', (0, 1), usd=0.001)
    write_run(tmp_path, inputs, 'bm25', (2, 0), totals=(20, 80))
    retriever = HybridRetriever(load_run(tmp_path, 'dense', 'dense', inputs, 'v1'),
                                load_run(tmp_path, 'bm25', 'bm25', inputs, 'v1'))
    with patch.object(hybrid, 'perf_counter', side_effect=(1, 1.002, 2, 2.003)):
        predictions = tuple(retriever.predict(query.query_id, 2) for query in inputs.queries)
    for prediction, total, fusion in zip(predictions, (102, 83), (2, 3), strict=True):
        assert prediction.timing is not None
        assert prediction.timing.kind == 'estimated'
        assert prediction.timing.total_ms == pytest.approx(total)
        assert prediction.timing.fusion_ms == pytest.approx(fusion)
        assert prediction.timing.query_encoding_ms is None
        assert prediction.timing.retrieval_ms is None
        assert prediction.cost is not None and prediction.cost.usd == 0.001
    args = argparse.Namespace(top_k=2, output_dir=tmp_path, corpus_version='v1', run_name='hybrid', queries=tmp_path/'queries.jsonl')
    save_results(args, inputs, predictions, {'retrieval_method': 'hybrid'}, ())
    assert load_predictions(tmp_path/'v1/runs/hybrid.jsonl') == predictions
    assert not (tmp_path / 'v1/runs/hybrid.predictions.jsonl').exists()


def test_원본_시간_누락은_추정하지_않는다(tmp_path: Path, inputs: Inputs) -> None:
    """원본 total_ms가 없으면 전체 시간은 null이고 RRF 시간은 유지한다."""
    write_run(tmp_path, inputs, 'dense', (0, 1), usd=0.001)
    write_run(tmp_path, inputs, 'bm25', (2, 0), totals=(None, 80))
    retriever = HybridRetriever(load_run(tmp_path, 'dense', 'dense', inputs, 'v1'),
                                load_run(tmp_path, 'bm25', 'bm25', inputs, 'v1'))
    prediction = retriever.predict('Q1', 2)
    assert prediction.timing is not None
    assert prediction.timing.total_ms is None
    assert prediction.timing.fusion_ms is not None
    assert prediction.cost is not None


def test_예측_파일_없으면_거절한다(tmp_path: Path, inputs: Inputs) -> None:
    """예측 JSONL이 없으면 융합하지 않는다."""
    write_run(tmp_path, inputs, 'dense', (0, 1))
    (tmp_path / 'runs/dense.jsonl').unlink()
    with pytest.raises(ValueError, match='예측 파일'):
        load_run(tmp_path, 'dense', 'dense', inputs, 'v1')


def test_구형_trec_run은_거절한다(tmp_path: Path, inputs: Inputs) -> None:
    """prediction_file이 없는 예전 TREC 산출물은 융합하지 않는다."""
    (tmp_path / 'runs').mkdir(exist_ok=True)
    (tmp_path / 'manifests').mkdir(exist_ok=True)
    (tmp_path / 'runs/dense.jsonl').write_text('{}\n', encoding='utf-8')
    (tmp_path / 'manifests/dense.json').write_text(json.dumps({
        'schema_version': 1, 'status': 'completed', 'run_id': 'dense',
        'retrieval_method': 'dense', 'ranking_unit': 'document',
        'tie_break': 'doc_id_ascending', 'corpus_version': 'v1',
        'corpus_sha256': 'a', 'query_sha256': 'b',
        'document_count': 3, 'query_count': 2,
        'run_file': 'runs/dense.jsonl', 'top_k': 2, 'result_count': 4,
    }))
    with pytest.raises(ValueError, match='예측 파일이 연결된 산출물'):
        load_run(tmp_path, 'dense', 'dense', inputs, 'v1')


@pytest.mark.parametrize('change', ('hash', 'query', 'path'))
def test_예측_파일_불일치를_거절한다(tmp_path: Path, inputs: Inputs, change: str) -> None:
    """해시·쿼리·경로가 다른 예측 파일을 융합 입력으로 쓰지 않는다."""
    write_run(tmp_path, inputs, 'dense', (0, 1))
    path = tmp_path/'runs/dense.jsonl'
    predictions = tuple(json.loads(line) for line in path.read_text().splitlines())
    extra = {}
    if change == 'query':
        extra = {'query_id': 'Q2'}
    elif change == 'hash':
        extra = {
            'candidates': ({**predictions[0]['candidates'][0], 'score': 99.0}, *predictions[0]['candidates'][1:]),
            'ranked': ({**predictions[0]['ranked'][0], 'score': 99.0}, *predictions[0]['ranked'][1:]),
        }
    changed = {**predictions[0], **extra}
    raw = ('\n'.join(json.dumps(item) for item in (changed, predictions[1])) + '\n').encode()
    path.write_bytes(raw)
    manifest_path = tmp_path/'manifests/dense.json'
    manifest = json.loads(manifest_path.read_text())
    manifest_path.write_text(json.dumps({**manifest,
        **({'prediction_sha256': sha256(raw)} if change != 'hash' else {}),
        **({'prediction_file': '../elsewhere.jsonl'} if change == 'path' else {})}))
    with pytest.raises(ValueError):
        load_run(tmp_path, 'dense', 'dense', inputs, 'v1')
