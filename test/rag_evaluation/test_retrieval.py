"""문서 단위 검색과 평가 산출물의 정합성을 검증한다."""

import argparse
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import Mock, patch
from uuid import UUID

import pytest

from RAG_evaluation.embedding.fixed_character import Document
from RAG_evaluation.retrieval import common, dense, lexical


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


@pytest.mark.parametrize('hits', [
    ((str(UUID(int=1)), 1.0), (str(UUID(int=1)), 0.9)),
    ((str(UUID(int=99)), 1.0), (str(UUID(int=2)), 0.9)),
    ((str(UUID(int=1)), float('nan')), (str(UUID(int=2)), 0.9)),
    ((str(UUID(int=2)), 0.5), (str(UUID(int=1)), 0.9)),
])
def test_잘못된_검색_결과를_저장_전에_거절(inputs: common.Inputs, hits: tuple[tuple[str, float], ...]) -> None:
    """중복·외부 공고·잘못된 점수·순서 오류를 거절한다."""
    with pytest.raises(ValueError):
        common.collect_results(inputs, 2, Mock(return_value=hits))


def test_manifest_결과_해시와_덮어쓰기_방지(inputs: common.Inputs, tmp_path: Path) -> None:
    """결과와 manifest를 연결하고 기존 실행 결과를 덮어쓰지 않는다."""
    args = argparse.Namespace(top_k=1, output_dir=tmp_path, corpus_version='v1', run_name='test', queries=tmp_path / 'queries.jsonl')
    rows = common.collect_results(inputs, 1, Mock(return_value=((str(UUID(int=1)), 1.0),)))
    common.save_results(args, inputs, rows, {'retrieval_method': 'test'}, perf_counter(), ())
    raw = (tmp_path / 'v1/runs/test.jsonl').read_bytes()
    manifest = json.loads((tmp_path / 'v1/manifests/test.json').read_text())
    assert manifest['run_sha256'] == common.sha256(raw)
    assert manifest['query_sha256'] == inputs.query_sha256
    assert json.loads(raw)['rank'] == 1
    with pytest.raises(FileExistsError):
        common.output_paths(args)


def test_query_힌트는_검색_입력에서_제외(inputs: common.Inputs, tmp_path: Path) -> None:
    """평가 힌트를 읽더라도 검색 함수에는 사용자 쿼리만 전달한다."""
    corpus_path, query_path = tmp_path / 'corpus.jsonl', tmp_path / 'queries.jsonl'
    corpus_path.write_text('\n'.join(doc.model_dump_json() for doc in inputs.documents))
    query_path.write_text(json.dumps({'query_id': 'Q001', 'query': 'MLOps', 'notes': '정답 공고', 'seed_hints': ['힌트']}))
    loaded = common.load_inputs(corpus_path, query_path)
    search = Mock(return_value=((str(UUID(int=1)), 1.0),))
    common.collect_results(loaded, 1, search)
    search.assert_called_once_with('MLOps', 1)


def test_dense_기존_입력과_run_격리() -> None:
    """기존 text 접두사·모델·차원과 지정된 run만 사용한다."""
    db, client = Mock(), Mock()
    db.rpc.return_value.execute.return_value.data = [{'doc_id': str(UUID(int=1)), 'score': 0.8}]
    run = {'run_id': 'selected-run', 'embedding_model': 'model', 'dimensions': 2,
           'config': {'query_template': 'text: {query}'}}
    with patch.object(dense, 'create_embedding', return_value=[1.0, 0.0]) as embed:
        result = dense.DenseRetriever(db, client, run).search('MLOps', 20)
    embed.assert_called_once_with(client, 'text: MLOps', model='model', dimensions=2)
    db.rpc.assert_called_once_with('match_eval_documents', {
        'p_run_id': 'selected-run', 'p_query_embedding': [1.0, 0.0], 'p_top_k': 20,
    })
    assert result == ((str(UUID(int=1)), 0.8),)


@pytest.mark.parametrize('status,corpus_hash', [('pending', 'a' * 64), ('completed', 'c' * 64)])
def test_dense_미완료와_corpus_불일치_차단(inputs: common.Inputs, status: str, corpus_hash: str) -> None:
    """다른 corpus나 미완료 벡터를 사용해 평가하지 않도록 한다."""
    db = Mock()
    db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{
        'status': status, 'corpus_version': 'v1', 'corpus_sha256': corpus_hash, 'expected_documents': 3,
    }]
    with pytest.raises(ValueError):
        dense.load_embedding_run(db, 'run', inputs, 'v1')
