"""문서 단위 검색과 평가 산출물의 정합성을 검증한다."""

import argparse
import json
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID

import pytest

from RAG_evaluation.benchmark.schema import Cost, Timing
from RAG_evaluation.benchmark.loader import load_predictions
from RAG_evaluation.benchmark.evaluator import evaluate
from RAG_evaluation.embedding.fixed_character import Document
from RAG_evaluation.retrieval import common, lexical, semantic


@pytest.fixture(scope='module')
def inputs() -> common.Inputs:
    """서로 다른 기술 직무를 가진 공고와 검색 쿼리를 준비한다."""
    documents = tuple(Document(
        id=UUID(int=index), title=title, content=content, url='https://example.com', metadata={},
    ) for index, title, content in (
        (1, 'MLOps 엔지니어', '머신러닝 배포 파이프라인 운영'),
        (2, 'React Native 개발자', '모바일 앱 개발'),
        (3, '정보보안 담당자', '보안 분석과 취약점 점검'),
    ))
    return common.Inputs(documents, (common.Query(query_id='Q001', query='MLOps'),), 'a' * 64, 'b' * 64)


@pytest.fixture(scope='module')
def retriever(inputs: common.Inputs) -> lexical.BM25Retriever:
    """실제 Kiwi와 BM25로 작은 검증 인덱스를 만든다."""
    return lexical.BM25Retriever.build(inputs, 1.5, 0.75, 0.25)


def test_bm25_기술명_검색과_대소문자(retriever: lexical.BM25Retriever) -> None:
    """실제 기술명 검색에서 해당 공고가 우선되고 대소문자를 통일한다."""
    assert retriever.search('MLOps', 3)[0][0] == str(UUID(int=1))
    assert retriever.search('React Native', 3)[0][0] == str(UUID(int=2))
    assert retriever.search('MLOps', 3) == retriever.search('mlops', 3)


def test_bm25_미일치_쿼리는_동점_ID순(retriever: lexical.BM25Retriever) -> None:
    """일치 토큰이 없어도 풀링용 0점 후보를 결정적인 순서로 반환한다."""
    assert retriever.search('zzzzqqqqxxxx', 2) == ((str(UUID(int=1)), 0.0), (str(UUID(int=2)), 0.0))


def test_bm25_단계별_시간_경계() -> None:
    """쿼리 정규화·토큰화와 점수 계산·정렬 시간을 구분해 반환한다."""
    events = Mock()
    events.clock.side_effect = (10.0, 10.003, 10.012)
    events.normalize.side_effect = lexical.normalize
    events.tokenize.return_value = ()
    events.scores.return_value = (1.0, 3.0, 3.0)
    events.sort.side_effect = sorted
    kiwi, index = Mock(), Mock()
    kiwi.tokenize = events.tokenize
    index.get_scores = events.scores
    retriever = lexical.BM25Retriever(('d1', 'd3', 'd2'), kiwi, index)
    with (
        patch.object(lexical, 'perf_counter', events.clock),
        patch.object(lexical, 'normalize', events.normalize),
        patch.object(lexical, 'sorted', events.sort, create=True),
    ):
        hits, timing = retriever.search_with_timing('MLOps', 2)
    assert hits == (('d2', 3.0), ('d3', 3.0))
    assert timing.kind == 'measured'
    assert timing.retrieval_ms == pytest.approx(9)
    assert timing.total_ms == pytest.approx(12)
    assert timing.query_encoding_ms == pytest.approx(3)
    assert timing.fusion_ms is None
    assert timing.rerank_ms is None
    assert tuple(call[0] for call in events.mock_calls) == (
        'clock', 'normalize', 'tokenize', 'clock', 'scores', 'sort', 'clock',
    )


@pytest.mark.parametrize('hits', [
    ((str(UUID(int=1)), 1.0), (str(UUID(int=1)), 0.9)),
    ((str(UUID(int=99)), 1.0), (str(UUID(int=2)), 0.9)),
    ((str(UUID(int=1)), float('nan')), (str(UUID(int=2)), 0.9)),
    ((str(UUID(int=2)), 0.5), (str(UUID(int=1)), 0.9)),
])
def test_잘못된_검색_결과를_저장_전에_거절(inputs: common.Inputs, hits: tuple[tuple[str, float], ...]) -> None:
    """중복·외부 공고·잘못된 점수·순서 오류를 거절한다."""
    with pytest.raises(ValueError):
        common.collect_results(inputs, 2, Mock(return_value=(hits, Timing(kind='measured', total_ms=10))))


def test_manifest_결과_해시와_덮어쓰기_방지(inputs: common.Inputs, tmp_path: Path) -> None:
    """결과와 manifest를 연결하고 기존 실행 결과를 덮어쓰지 않는다."""
    args = argparse.Namespace(top_k=1, output_dir=tmp_path, corpus_version='v1', run_name='test', queries=tmp_path / 'queries.jsonl')
    rows = common.collect_results(inputs, 1, Mock(return_value=(((str(UUID(int=1)), 1.0),), Timing(kind='measured', total_ms=10))))
    common.save_results(args, inputs, rows, {'retrieval_method': 'test'}, ())
    run_path = tmp_path / 'v1/runs/test.jsonl'
    manifest = json.loads((tmp_path / 'v1/manifests/test.json').read_text())
    assert not (tmp_path / 'v1/runs/test.predictions.jsonl').exists()
    assert manifest['prediction_sha256'] == common.sha256(run_path.read_bytes())
    assert manifest['query_sha256'] == inputs.query_sha256
    assert 'elapsed_seconds' not in manifest
    assert 'run_file' not in manifest
    assert load_predictions(run_path) == rows
    assert manifest['prediction_count'] == 1
    assert manifest['prediction_file'] == 'runs/test.jsonl'
    report = evaluate(load_predictions(run_path), {'Q001': {str(UUID(int=1)): 2}},
                      run_id='test', qrels_version='test')
    assert report.system is not None
    assert report.system.p95_latency_ms == 10
    with pytest.raises(FileExistsError):
        common.output_paths(args)


def test_쿼리별_계측값을_예측에_보존한다(inputs: common.Inputs) -> None:
    """각 쿼리의 시간·비용·후보 순위를 보존하고 미실행 단계는 null로 둔다."""
    queries = (common.Query(query_id='Q001', query='MLOps'), common.Query(query_id='Q002', query='React'))
    test_inputs = common.Inputs(inputs.documents, queries, inputs.corpus_sha256, inputs.query_sha256)
    first = Timing(kind='measured', query_encoding_ms=2, retrieval_ms=8, total_ms=10)
    second = Timing(kind='measured', query_encoding_ms=3, retrieval_ms=17, total_ms=20)
    cost = Cost(usd=0.00001)
    search = Mock(side_effect=(
        (((str(UUID(int=1)), 0.9), (str(UUID(int=2)), 0.5)), first, cost),
        (((str(UUID(int=2)), 0.8), (str(UUID(int=3)), 0.4)), second),
    ))
    predictions = common.collect_results(test_inputs, 2, search)
    assert tuple(item.query_id for item in predictions) == ('Q001', 'Q002')
    assert tuple(item.timing for item in predictions) == (first, second)
    assert tuple(hit.doc_id for hit in predictions[1].candidates) == (str(UUID(int=2)), str(UUID(int=3)))
    assert predictions[0].cost == cost
    assert predictions[1].cost is None
    for item in predictions:
        assert tuple(hit.rank for hit in item.candidates) == (1, 2)
        assert item.ranked == item.candidates
        assert item.recommended is None


def test_이전_predictions_접미사_파일도_덮어쓰기를_거절한다(tmp_path: Path) -> None:
    """잠시 쓰던 .predictions.jsonl이 남아 있으면 같은 run 이름을 쓰지 않는다."""
    directory = tmp_path / 'v1/runs'
    directory.mkdir(parents=True)
    (directory / 'test.predictions.jsonl').write_text('existing', encoding='utf-8')
    args = argparse.Namespace(top_k=1, output_dir=tmp_path, corpus_version='v1', run_name='test')
    with pytest.raises(FileExistsError):
        common.output_paths(args)


def test_기존_run_jsonl이_있으면_덮어쓰기를_거절한다(tmp_path: Path) -> None:
    """같은 이름의 jsonl이 있으면 새 예측 파일을 만들지 않는다."""
    directory = tmp_path / 'v1/runs'
    directory.mkdir(parents=True)
    (directory / 'test.jsonl').write_text('legacy', encoding='utf-8')
    args = argparse.Namespace(top_k=1, output_dir=tmp_path, corpus_version='v1', run_name='test')
    with pytest.raises(FileExistsError):
        common.output_paths(args)


def test_query_힌트는_검색_입력에서_제외(inputs: common.Inputs, tmp_path: Path) -> None:
    """평가 힌트를 읽더라도 검색 함수에는 사용자 쿼리만 전달한다."""
    corpus_path, query_path = tmp_path / 'corpus.jsonl', tmp_path / 'queries.jsonl'
    corpus_path.write_text('\n'.join(doc.model_dump_json() for doc in inputs.documents))
    query_path.write_text(json.dumps({'query_id': 'Q001', 'query': 'MLOps', 'notes': '정답 공고', 'seed_hints': ['힌트']}))
    loaded = common.load_inputs(corpus_path, query_path)
    search = Mock(return_value=(((str(UUID(int=1)), 1.0),), Timing(kind='measured', total_ms=10)))
    common.collect_results(loaded, 1, search)
    search.assert_called_once_with('MLOps', 1)


def test_dense_기존_입력과_run_격리() -> None:
    """기존 text 접두사·모델·차원과 지정된 run만 사용한다."""
    db, client = Mock(), Mock()
    db.rpc.return_value.execute.return_value.data = [{'doc_id': str(UUID(int=1)), 'score': 0.8}]
    run = {'run_id': 'selected-run', 'embedding_model': 'model', 'dimensions': 2,
           'config': {'query_template': 'text: {query}'}}
    with patch.object(semantic, 'create_embedding_with_cost', return_value=([1.0, 0.0], 0.00001)) as embed:
        result = semantic.DenseRetriever(db, client, run).search('MLOps', 20)
    embed.assert_called_once_with(client, 'text: MLOps', model='model', dimensions=2)
    db.rpc.assert_called_once_with('match_eval_documents', {
        'p_run_id': 'selected-run', 'p_query_embedding': [1.0, 0.0], 'p_top_k': 20,
    })
    assert result == ((str(UUID(int=1)), 0.8),)


def test_dense_단계별_시간_경계() -> None:
    """임베딩 검증과 결과 변환까지 포함해 단계별 시간을 밀리초로 반환한다."""
    db, client = Mock(), Mock()
    run = {'run_id': 'selected-run', 'embedding_model': 'model', 'dimensions': 2,
           'config': {'query_template': 'text: {query}'}}
    events = Mock()
    events.clock.side_effect = (10.0, 10.025, 10.1)
    events.embed.return_value = ([1.0, 0.0], 0.00001)
    with (
        patch.object(semantic, 'perf_counter', events.clock),
        patch.object(semantic, 'create_embedding_with_cost', events.embed),
        patch.object(semantic, 'validate_embedding', events.validate),
    ):
        events.attach_mock(db.rpc, 'rpc')
        # 이터레이터 소비 시점을 기록해 결과 변환도 측정 구간인지 확인한다.
        db.rpc.return_value.execute.return_value.data = map(
            events.convert, ({'doc_id': str(UUID(int=1)), 'score': 0.8},),
        )
        events.convert.side_effect = lambda row: row
        hits, timing, cost = semantic.DenseRetriever(db, client, run).search_with_timing('MLOps', 20)

    assert hits == ((str(UUID(int=1)), 0.8),)
    assert timing.kind == 'measured'
    assert cost is not None and cost.usd == 0.00001
    assert timing.query_encoding_ms == pytest.approx(25)
    assert timing.retrieval_ms == pytest.approx(75)
    assert timing.total_ms == pytest.approx(100)
    assert timing.fusion_ms is None
    assert timing.rerank_ms is None
    assert tuple(call[0] for call in events.mock_calls) == (
        'clock', 'embed', 'validate', 'clock', 'rpc', 'rpc().execute', 'convert', 'clock',
    )


def test_dense_비용_미제공은_null() -> None:
    """usage.cost가 없으면 검색은 하고 비용만 null로 둔다."""
    db, client = Mock(), Mock()
    db.rpc.return_value.execute.return_value.data = [{'doc_id': str(UUID(int=1)), 'score': 0.8}]
    run = {'run_id': 'selected-run', 'embedding_model': 'model', 'dimensions': 2,
           'config': {'query_template': 'text: {query}'}}
    with patch.object(semantic, 'create_embedding_with_cost', return_value=([1.0, 0.0], None)):
        _, _, cost = semantic.DenseRetriever(db, client, run).search_with_timing('MLOps', 20)
    assert cost is None
    db.rpc.assert_called_once()


def test_dense_임베딩_실패는_검색_전에_전파한다() -> None:
    """임베딩 실패 시 DB 검색이나 성공 계측 결과를 만들지 않는다."""
    db, client = Mock(), Mock()
    run = {'run_id': 'selected-run', 'embedding_model': 'model', 'dimensions': 2,
           'config': {'query_template': 'text: {query}'}}
    with patch.object(semantic, 'create_embedding_with_cost', side_effect=RuntimeError('embedding failed')):
        with pytest.raises(RuntimeError, match='embedding failed'):
            semantic.DenseRetriever(db, client, run).search_with_timing('MLOps', 20)
    db.rpc.assert_not_called()


@pytest.mark.parametrize('status,corpus_hash', [('pending', 'a' * 64), ('completed', 'c' * 64)])
def test_dense_미완료와_corpus_불일치_차단(inputs: common.Inputs, status: str, corpus_hash: str) -> None:
    """다른 corpus나 미완료 벡터를 사용해 평가하지 않도록 한다."""
    db = Mock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{
        'status': status, 'corpus_version': 'v1', 'corpus_sha256': corpus_hash, 'expected_documents': 3,
    }]
    with pytest.raises(ValueError):
        semantic.load_embedding_run(db, 'run', inputs, 'v1')
