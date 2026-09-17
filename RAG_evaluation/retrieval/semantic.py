"""평가용 pgvector Dense 검색 결과와 manifest를 저장한다."""

import sys
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from dotenv import load_dotenv
from openai import OpenAI
from postgrest.types import CountMethod
from supabase import Client

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from RAG_evaluation.embedding.fixed_character import validate_embedding
from RAG_evaluation.retrieval.common import (
    Inputs, argument_parser, collect_results, load_inputs, output_paths, save_results,
)
from integrations.clients import create_embedding, create_openrouter_client, create_supabase_client


def load_embedding_run(db: Client, name: str, inputs: Inputs, corpus_version: str) -> dict[str, Any]:
    """완료된 run의 corpus·건수·provider가 현재 검색 입력과 일치하는지 검사한다."""
    # 기존에 임베딩이 되어 있는 임베딩들을 eval_embedding_runs에서 선택해서 가져와서 처리 -> 그럼
    runs = cast(
        list[dict[str, Any]],
        db.table('eval_embedding_runs').select('*').eq('name', name).execute().data,
    )

    if len(runs) != 1 or runs[0]['status'] != 'completed':
        raise ValueError('검색에는 완료된 embedding run이 필요합니다')

    # 첫 번째 행
    run = runs[0]
    if (run['corpus_version'], run['corpus_sha256'], run['expected_documents']) != (
        corpus_version, inputs.corpus_sha256, len(inputs.documents),
    ):
        raise ValueError('embedding run의 corpus 버전·해시·건수가 입력과 다릅니다')
    if run['config']['provider'] != 'openrouter' or not run['config'].get('query_template'):
        raise ValueError('지원하는 provider와 query_template이 필요합니다')

    for table, column, value, expected in (
        # TODO expected documents가 있다..?
        ('eval_documents', 'corpus_version', corpus_version, run['expected_documents']),
        ('eval_chunks', 'run_id', run['run_id'], run['expected_chunks']),
    ):
        count = db.table(table).select('*', count=CountMethod.exact, head=True).eq(column, value).execute().count
        if count != expected:
            raise ValueError(f'{table}의 실제 건수가 embedding run과 다릅니다')
    return run


@dataclass(frozen=True)
class DenseRetriever:
    """한 embedding run에 고정된 코사인 유사도 검색기."""

    db: Client
    client: OpenAI
    run: dict[str, Any]

    def search(self, query: str, top_k: int) -> tuple[tuple[str, float], ...]:
        """기존 쿼리 입력 형식으로 임베딩하고 공고별 최고 점수를 조회한다."""
        # 쿼리 임베딩
        embedding = create_embedding(
            self.client, self.run['config']['query_template'].format(query=query),
            model=self.run['embedding_model'], dimensions=self.run['dimensions'],
        )

        validate_embedding(embedding, self.run['dimensions'])

        # 검증 및 retrieval
        rows = cast(list[dict[str, Any]], self.db.rpc('match_eval_documents', {
            'p_run_id': self.run['run_id'], 'p_query_embedding': embedding, 'p_top_k': top_k,
        }).execute().data)

        return tuple((str(row['doc_id']), float(row['score'])) for row in rows)


def main() -> None:
    """평가 Dense 검색을 실행해 run과 재현 설정을 저장한다."""
    # 실행 시간 기록
    started_at = perf_counter()

    # 커맨드라인 인자 파서
    # __doc__ -> 이 파일 맨 위의 주석으로 parser의 description으로 들어감
    # dense_fixed1000_qwen1536_v1 -> default run name
    parser = argument_parser(__doc__ or 'dense retrieval', 'dense_fixed1000_qwen1536_v1')
    # 이 이름에 맞는 임베딩 버전을 가져오기에 아무렇게 지으면 안됨
    parser.add_argument('--embedding-run-name', default='fixed1000_qwen1536_v1')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env.local')
    args = parser.parse_args()
    output_paths(args)

    inputs = load_inputs(args.corpus, args.queries)
    if not args.env_file.is_file():
        parser.error(f'환경 파일이 없습니다: {args.env_file}')

    # .env load
    load_dotenv(ROOT / '.env')
    # .env.local load
    load_dotenv(args.env_file, override=True)

    db = create_supabase_client()
    run = load_embedding_run(db, args.embedding_run_name, inputs, args.corpus_version)
    retriever = DenseRetriever(db, create_openrouter_client(), run)

    rows = collect_results(inputs, args.top_k, retriever.search)

    save_results(args, inputs, rows, {
        'retrieval_method': 'dense', 'embedding_run_id': run['run_id'],
        'embedding_run_name': run['name'], 'model': run['embedding_model'],
        'dimensions': run['dimensions'], 'embedding_config': run['config'],
        'similarity': 'cosine', 'chunk_aggregation': 'max', 'search_mode': 'exact',
        'rpc': 'match_eval_documents',
        'packages': {name: version(name) for name in ('openai', 'supabase')},
    }, started_at, (
        Path(__file__), ROOT / 'RAG_evaluation/retrieval/common.py',
        ROOT / 'integrations/clients.py',
        ROOT / 'supabase/migrations/20260909010000_add_eval_dense_search.sql',
    ))


if __name__ == '__main__':
    main()
