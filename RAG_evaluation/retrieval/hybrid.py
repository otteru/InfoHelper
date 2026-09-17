"""저장된 Dense·BM25 검색 결과를 검증하고 RRF 순위로 결합한다."""

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from RAG_evaluation.retrieval.common import (
    Inputs, argument_parser, load_inputs, output_paths, save_results, sha256,
)


class RunRow(BaseModel):
    """저장된 검색 결과의 공고 순위와 유한 점수."""

    model_config = ConfigDict(frozen=True, strict=True)
    query_id: str
    doc_id: str
    rank: int = Field(ge=1)
    score: float = Field(allow_inf_nan=False)


@dataclass(frozen=True)
class SavedRun:
    """검증한 검색 결과와 원본 추적 정보."""

    rows: tuple[RunRow, ...]
    run_id: str
    run_sha256: str
    manifest_sha256: str
    manifest_path: Path
    top_k: int

    def ranking(self, query_id: str, top_k: int) -> tuple[str, ...]:
        """쿼리 ID에 해당하는 저장 순위의 상위 공고 ID를 반환한다."""
        return tuple(row.doc_id for row in self.rows if row.query_id == query_id)[:top_k]

    def provenance(self) -> dict[str, Any]:
        """Hybrid manifest에 기록할 원본 run 식별 정보와 해시를 반환한다."""
        return {
            'run_id': self.run_id, 'run_sha256': self.run_sha256,
            'manifest_sha256': self.manifest_sha256,
            'manifest_file': str(self.manifest_path.resolve()), 'top_k': self.top_k,
        }


def load_run(
    directory: Path, name: str, method: str, inputs: Inputs, corpus_version: str,
) -> SavedRun:
    """완료 manifest와 입력 해시·건수·문서별 순위의 정합성을 검사한다."""
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
        'run_file': f'runs/{name}.jsonl',
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError(f'{name}: manifest의 실험 설정 또는 입력이 다릅니다')
    top_k = manifest.get('top_k')
    if type(top_k) is not int or not 1 <= top_k <= 1000:
        raise ValueError(f'{name}: top-k가 올바르지 않습니다')
    raw = (directory / 'runs' / f'{name}.jsonl').read_bytes()
    if sha256(raw) != manifest.get('run_sha256'):
        raise ValueError(f'{name}: 결과 파일 해시가 다릅니다')
    rows = tuple(RunRow.model_validate_json(line) for line in raw.splitlines() if line.strip())
    count = min(top_k, len(inputs.documents))
    if len(rows) != count * len(inputs.queries) or manifest.get('result_count') != len(rows):
        raise ValueError(f'{name}: 결과 건수가 다릅니다')
    if {row.query_id for row in rows} != {query.query_id for query in inputs.queries}:
        raise ValueError(f'{name}: 쿼리 ID가 다릅니다')
    allowed = frozenset(str(doc.id) for doc in inputs.documents)
    for query in inputs.queries:
        hits = tuple(row for row in rows if row.query_id == query.query_id)
        if (len(hits) != count or len({row.doc_id for row in hits}) != count
                or any(row.doc_id not in allowed for row in hits)
                or tuple(row.rank for row in hits) != tuple(range(1, count + 1))
                or hits != tuple(sorted(hits, key=lambda row: (-row.score, row.doc_id)))):
            raise ValueError(f'{name}: {query.query_id}의 공고 또는 순위가 올바르지 않습니다')
    return SavedRun(rows, name, sha256(raw), sha256(manifest_raw), manifest_path, top_k)


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
        if not 1 <= top_k <= min(1000, self.dense.top_k, self.bm25.top_k):
            raise ValueError('top-k는 1 이상이며 두 원본 run의 top-k 이하여야 합니다')
        rankings = (self.dense.ranking(query_id, top_k), self.bm25.ranking(query_id, top_k))
        if not all(rankings):
            raise ValueError(f'두 run에 쿼리 ID가 필요합니다: {query_id}')
        rank_scores = tuple(
            {doc_id: 1.0 / (self.rrf_k + rank) for rank, doc_id in enumerate(hits, start=1)}
            for hits in rankings
        )
        doc_ids = frozenset(doc_id for scores in rank_scores for doc_id in scores)
        hits = tuple((doc_id, sum(scores.get(doc_id, 0.0) for scores in rank_scores)) for doc_id in doc_ids)
        return tuple(sorted(hits, key=lambda hit: (-hit[1], hit[0]))[:top_k])


def main() -> None:
    """저장된 run을 융합하고 결과와 원본 해시를 새 manifest에 저장한다."""
    started_at = perf_counter()
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
    rows = tuple(
        {'query_id': query.query_id, 'doc_id': doc_id, 'rank': rank, 'score': score}
        for query in inputs.queries
        for rank, (doc_id, score) in enumerate(retriever.search(query.query_id, args.top_k), start=1)
    )
    save_results(args, inputs, rows, {
        'retrieval_method': 'hybrid', 'fusion': 'rrf', 'rrf_k': args.rrf_k,
        'input_mode': 'saved_runs', 'candidate_top_k': args.top_k,
        'weights': {'dense': 1, 'bm25': 1},
        'source_runs': {'dense': dense.provenance(), 'bm25': bm25.provenance()},
    }, started_at, (Path(__file__), ROOT / 'RAG_evaluation/retrieval/common.py'))


if __name__ == '__main__':
    main()
