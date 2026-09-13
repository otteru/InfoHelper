"""검색기 공통 입력 검증과 run·manifest 저장을 제공한다."""

import argparse
import hashlib
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from RAG_evaluation.embedding.fixed_character import Document

ROOT = Path(__file__).resolve().parents[2]


class Query(BaseModel):
    """검색에 사용할 식별자와 사용자 쿼리."""

    model_config = ConfigDict(frozen=True)
    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)


@dataclass(frozen=True)
class Inputs:
    """동일 corpus·query 파일을 식별하는 검색 입력 묶음."""

    documents: tuple[Document, ...]
    queries: tuple[Query, ...]
    corpus_sha256: str
    query_sha256: str


def sha256(data: bytes) -> str:
    """바이트의 SHA-256 해시를 반환한다."""
    return hashlib.sha256(data).hexdigest()


def load_inputs(corpus_path: Path, query_path: Path) -> Inputs:
    """ID 중복과 빈 입력을 검사하며 검색 데이터와 파일 해시를 읽는다."""
    corpus_raw, query_raw = corpus_path.read_bytes(), query_path.read_bytes()
    documents = tuple(Document.model_validate_json(line) for line in corpus_raw.splitlines() if line.strip())
    queries = tuple(Query.model_validate_json(line) for line in query_raw.splitlines() if line.strip())

    if not documents or len({doc.id for doc in documents}) != len(documents):
        raise ValueError('corpus가 비어 있거나 공고 ID가 중복됩니다')
    if not queries or len({query.query_id for query in queries}) != len(queries):
        raise ValueError('쿼리가 비어 있거나 query_id가 중복됩니다')
    if any(not query.query.strip() or not query.query_id.strip() for query in queries):
        raise ValueError('공백으로만 이루어진 쿼리 또는 query_id는 사용할 수 없습니다')
    return Inputs(documents, queries, sha256(corpus_raw), sha256(query_raw))


def argument_parser(description: str, run_name: str) -> argparse.ArgumentParser:
    """두 검색기에 동일한 corpus·query·출력 옵션을 제공한다."""
    parser = argparse.ArgumentParser(description=description)
    #TODO 이거 clean된 corpus로 변경해야 하는지 확인
    parser.add_argument('--corpus', type=Path, default=ROOT / 'RAG_evaluation/dataset/zighang/corpus.jsonl')
    parser.add_argument('--queries', type=Path, default=ROOT / 'RAG_evaluation/dataset/zighang/queries/eval_queries_80.jsonl')
    parser.add_argument('--corpus-version', default='zighang_v1')
    parser.add_argument('--run-name', default=run_name)
    parser.add_argument('--top-k', type=int, default=20)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'RAG_evaluation/artifacts')
    return parser


def  output_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    """출력 식별자를 검사하고 기존 결과 덮어쓰기를 실행 전에 막는다."""
    if not 1 <= args.top_k <= 1000:
        raise ValueError('top-k는 1~1000이어야 합니다')

    for value in (args.corpus_version, args.run_name):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', value):
            raise ValueError('버전과 run 이름은 영문·숫자·밑줄·하이픈만 사용할 수 있습니다')

    directory = args.output_dir / args.corpus_version
    paths = (directory / 'runs' / f'{args.run_name}.jsonl',
             directory / 'manifests' / f'{args.run_name}.json')

    if any(path.exists() for path in paths):
        raise FileExistsError('같은 이름의 결과가 있습니다. 새 --run-name을 사용하세요')
    return paths


def collect_results(
    inputs: Inputs, top_k: int, search: Callable[[str, int], tuple[tuple[str, float], ...]],
) -> tuple[dict[str, Any], ...]:
    """쿼리별 고유 공고 순위·점수를 검증하고 공통 결과 행을 생성한다."""

    allowed = frozenset(str(doc.id) for doc in inputs.documents)
    rows: tuple[dict[str, Any], ...] = ()

    for index, query in enumerate(inputs.queries, start=1):
        # search 파라미터에 함수 자체를 넘긴다고 보면 됨
        # 반환 값으로 ((doc_id, score), ...) 튜플 제공
        hits = search(query.query, top_k)
        if len(hits) != min(top_k, len(allowed)) or len({doc_id for doc_id, _ in hits}) != len(hits):
            raise ValueError('검색 결과의 공고 수 또는 중복 여부가 올바르지 않습니다')

        if any(doc_id not in allowed or not math.isfinite(score) for doc_id, score in hits):
            raise ValueError('검색 결과에 corpus 외 공고 또는 잘못된 점수가 있습니다')

        # 점수 내림차순, ID 오름차순으로 되어 있는지 확인
        if hits != tuple(sorted(hits, key=lambda hit: (-hit[1], hit[0]))):
            raise ValueError('검색 결과가 점수 내림차순·ID 오름차순이 아닙니다')

        rows = (*rows, *({'query_id': query.query_id, 'doc_id': doc_id, 'rank': rank, 'score': score}
                        for rank, (doc_id, score) in enumerate(hits, start=1)))
        print(f'검색 완료: {index}/{len(inputs.queries)} ({query.query_id})', flush=True)

    return rows


def save_results(
    args: argparse.Namespace, inputs: Inputs, rows: tuple[dict[str, Any], ...],
    settings: dict[str, Any], started_at: float, code_files: tuple[Path, ...],
) -> None:
    """완성된 run과 결과 해시를 포함한 manifest를 배타적으로 저장한다."""
    run_path, manifest_path = output_paths(args)
    data = ''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n' for row in rows)
    manifest = {
        'schema_version': 1, 'status': 'completed', 'run_id': args.run_name,
        'corpus_version': args.corpus_version, 'corpus_sha256': inputs.corpus_sha256,
        'query_file': str(args.queries.resolve()), 'query_sha256': inputs.query_sha256,
        'document_count': len(inputs.documents), 'query_count': len(inputs.queries),
        'result_count': len(rows), 'top_k': args.top_k,
        'ranking_unit': 'document', 'tie_break': 'doc_id_ascending', 'score_threshold': None,
        'run_file': f'runs/{args.run_name}.jsonl', 'run_sha256': sha256(data.encode('utf-8')),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'elapsed_seconds': round(perf_counter() - started_at, 3),
        'code_sha256': {str(path.relative_to(ROOT)): sha256(path.read_bytes()) for path in code_files},
        **settings,
    }

    run_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with run_path.open('x', encoding='utf-8') as file:
        file.write(data)
    # manifest가 존재하는 결과만 완성된 산출물로 취급한다.
    with manifest_path.open('x', encoding='utf-8') as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write('\n')
    print(f'저장 완료: {run_path}\n설정 기록: {manifest_path}')