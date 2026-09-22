"""저장된 Dense·BM25 검색 결과를 검증하고 RRF 순위로 결합한다."""

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from RAG_evaluation.retrieval.common import (
    Inputs, argument_parser, load_inputs, output_paths, save_results, sha256,
)
from RAG_evaluation.benchmark.schema import Cost, Hit, QueryPrediction, Timing


@dataclass(frozen=True)
class SavedRun:
    """검증한 예측 결과와 원본 추적 정보."""

    predictions: tuple[QueryPrediction, ...]
    run_id: str
    prediction_sha256: str
    manifest_sha256: str
    manifest_path: Path
    top_k: int

    def ranking(self, query_id: str, top_k: int) -> tuple[str, ...]:
        """쿼리 ID에 해당하는 저장 순위의 상위 공고 ID를 반환한다."""
        prediction = next((item for item in self.predictions if item.query_id == query_id), None)
        if prediction is None:
            return ()
        return tuple(hit.doc_id for hit in sorted(prediction.candidates, key=lambda hit: hit.rank))[:top_k]

    def provenance(self) -> dict[str, Any]:
        """Hybrid manifest에 기록할 원본 run 식별 정보와 해시를 반환한다."""
        return {
            'run_id': self.run_id, 'prediction_sha256': self.prediction_sha256,
            'manifest_sha256': self.manifest_sha256,
            'manifest_file': str(self.manifest_path.resolve()), 'top_k': self.top_k,
        }


def load_run(
    directory: Path, name: str, method: str, inputs: Inputs, corpus_version: str,
) -> SavedRun:
    """완료 manifest와 예측 파일 해시·건수·문서별 순위의 정합성을 검사한다."""
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', name):
        raise ValueError('입력 run 이름이 올바르지 않습니다')
    manifest_path = directory / 'manifests' / f'{name}.json'
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    expected = {
        'schema_version': 1, 'status': 'completed', 'run_id': name,
        'retrieval_method': method, 'ranking_unit': 'document',
        'tie_break': 'doc_id_ascending', 'corpus_version': corpus_version,
        'corpus_sha256': inputs.corpus_sha256, 'query_sha256': inputs.query_sha256,
        'document_count': len(inputs.documents), 'query_count': len(inputs.queries),
        'prediction_file': f'runs/{name}.jsonl',
    }
    if manifest.get('prediction_file') != expected['prediction_file']:
        raise ValueError(f'{name}: 예측 파일이 연결된 산출물이 아닙니다')
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError(f'{name}: manifest의 실험 설정 또는 입력이 다릅니다')
    top_k = manifest.get('top_k')
    if type(top_k) is not int or not 1 <= top_k <= 1000:
        raise ValueError(f'{name}: top-k가 올바르지 않습니다')
    prediction_path = directory / 'runs' / f'{name}.jsonl'
    if not prediction_path.is_file():
        raise ValueError(f'{name}: 예측 파일이 없습니다')
    raw = prediction_path.read_bytes()
    if sha256(raw) != manifest.get('prediction_sha256'):
        raise ValueError(f'{name}: 예측 파일 해시가 다릅니다')
    predictions = tuple(QueryPrediction.model_validate_json(line) for line in raw.splitlines() if line.strip())
    count = min(top_k, len(inputs.documents))
    if (len(predictions) != len(inputs.queries)
            or manifest.get('prediction_count') != len(predictions)
            or manifest.get('result_count') != count * len(inputs.queries)
            or len({item.query_id for item in predictions}) != len(predictions)
            or {item.query_id for item in predictions} != {query.query_id for query in inputs.queries}):
        raise ValueError(f'{name}: 예측 쿼리 ID 또는 건수가 다릅니다')
    allowed = frozenset(str(doc.id) for doc in inputs.documents)
    for prediction in predictions:
        hits = prediction.candidates
        if (len(hits) != count or any(hit.doc_id not in allowed for hit in hits)
                or hits != tuple(sorted(hits, key=lambda hit: (-hit.score, hit.doc_id)))):
            raise ValueError(f'{name}: {prediction.query_id}의 공고 또는 순위가 올바르지 않습니다')
    return SavedRun(predictions, name, sha256(raw), sha256(manifest_raw), manifest_path, top_k)


@dataclass(frozen=True)
class HybridRetriever:
    """두 저장 run의 공고 순위를 동일 가중치 RRF로 결합한다."""

    dense: SavedRun
    bm25: SavedRun
    rrf_k: int = 60

    def __post_init__(self) -> None:
        """RRF 순위 보정 상수가 양의 정수인지 확인한다."""
        if type(self.rrf_k) is not int or self.rrf_k <= 0:
            raise ValueError('rrf-k는 양의 정수여야 합니다')

    def search(self, query_id: str, top_k: int) -> tuple[tuple[str, float], ...]:
        """쿼리 ID로 저장된 top-k를 읽어 RRF 공고 top-k를 반환한다."""
        hits, _ = self.search_with_timing(query_id, top_k)
        return hits

    def search_with_timing(
        self, query_id: str, top_k: int,
    ) -> tuple[tuple[tuple[str, float], ...], Timing]:
        """RRF 결합 시간을 측정하고 원본 쿼리별 시간으로 병렬 실행 시간을 추정한다."""
        if not 1 <= top_k <= min(1000, self.dense.top_k, self.bm25.top_k):
            raise ValueError('top-k는 1 이상이며 두 원본 run의 top-k 이하여야 합니다')
        rankings = (self.dense.ranking(query_id, top_k), self.bm25.ranking(query_id, top_k))
        if not all(rankings):
            raise ValueError(f'두 run에 쿼리 ID가 필요합니다: {query_id}')
        started = perf_counter()
        rank_scores = tuple(
            {doc_id: 1.0 / (self.rrf_k + rank) for rank, doc_id in enumerate(hits, start=1)}
            for hits in rankings
        )
        doc_ids = frozenset(doc_id for scores in rank_scores for doc_id in scores)
        hits = tuple((doc_id, sum(scores.get(doc_id, 0.0) for scores in rank_scores)) for doc_id in doc_ids)
        results = tuple(sorted(hits, key=lambda hit: (-hit[1], hit[0]))[:top_k])
        fusion_ms = (perf_counter() - started) * 1000
        totals = tuple(
            prediction.timing.total_ms
            for run in (self.dense, self.bm25)
            for prediction in run.predictions
            if prediction.query_id == query_id and prediction.timing is not None
            and prediction.timing.total_ms is not None
        )
        return results, Timing(
            kind='estimated', fusion_ms=fusion_ms,
            total_ms=max(totals) + fusion_ms if len(totals) == 2 else None,
        )

    def predict(self, query_id: str, top_k: int) -> QueryPrediction:
        """결합 순위와 추정 시간 및 원본 API 비용 합계를 쿼리별 예측으로 만든다."""
        hits, timing = self.search_with_timing(query_id, top_k)
        candidates = tuple(Hit(doc_id=doc_id, rank=rank, score=score)
                           for rank, (doc_id, score) in enumerate(hits, 1))
        costs = tuple(prediction.cost.usd for run in (self.dense, self.bm25)
                      for prediction in run.predictions
                      if prediction.query_id == query_id and prediction.cost is not None)
        return QueryPrediction(
            query_id=query_id, candidates=candidates, ranked=candidates, timing=timing,
            cost=Cost(usd=sum(costs)) if len(costs) == 2 else None,
        )


def main() -> None:
    """저장된 run을 융합하고 결과와 원본 해시를 새 manifest에 저장한다."""
    # argument_parser에서 공통적인 값들은 채운다.
    parser = argument_parser(__doc__ or 'hybrid retrieval', 'hybrid_rrf60_saved_v1')
    parser.add_argument('--input-dir', type=Path, default=ROOT / 'RAG_evaluation/artifacts')
    parser.add_argument('--dense-run-name', default='dense_fixed1000_qwen1536_v1')
    parser.add_argument('--bm25-run-name', default='bm25_kiwi_v1')
    parser.add_argument('--rrf-k', type=int, default=60)
    args = parser.parse_args()
    
    output_paths(args)
    
    if args.rrf_k <= 0:
        parser.error('rrf-k는 양의 정수여야 합니다')
        
    inputs = load_inputs(args.corpus, args.queries)
    
    directory = args.input_dir / args.corpus_version
    
    dense = load_run(directory, args.dense_run_name, 'dense', inputs, args.corpus_version)
    bm25 = load_run(directory, args.bm25_run_name, 'bm25', inputs, args.corpus_version)
    
    retriever = HybridRetriever(dense, bm25, args.rrf_k)
    predictions = tuple(retriever.predict(query.query_id, args.top_k) for query in inputs.queries)
    
    save_results(args, inputs, predictions, {
        'retrieval_method': 'hybrid', 'fusion': 'rrf', 'rrf_k': args.rrf_k,
        'input_mode': 'saved_runs', 'candidate_top_k': args.top_k,
        'timing_method': 'max_source_total_ms_plus_fusion_ms',
        'weights': {'dense': 1, 'bm25': 1},
        'source_runs': {'dense': dense.provenance(), 'bm25': bm25.provenance()},
    }, (Path(__file__), ROOT / 'RAG_evaluation/retrieval/common.py'))


if __name__ == '__main__':
    main()
