"""저장된 검색 결과에서 기존 pool에 없는 쿼리–공고 쌍을 추출한다."""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from RAG_evaluation.benchmark.loader import load_predictions, load_qrels
from RAG_evaluation.retrieval.common import load_inputs

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / 'RAG_evaluation/dataset'
ARTIFACTS = ROOT / 'RAG_evaluation/artifacts/zighang_v1'
GUIDELINES = ROOT / 'docs/labeling-guidelines.md'


def find_unjudged(filename: str, pool_version: str) -> Path | None:
    """미평가 쌍의 원문과 추적 정보를 저장하고 신규 대상이 없으면 None을 반환한다."""
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*\.jsonl', filename):
        raise ValueError('경로 없이 runs의 .jsonl 파일명을 입력하세요')
    if not re.fullmatch(r'pool_v[1-9][0-9]*', pool_version):
        raise ValueError('pool 버전은 pool_v1 형식이어야 합니다')
    run_path = ARTIFACTS / 'runs' / filename
    qrels_path = DATASET / 'labeling' / pool_version / 'qrels.txt'
    predictions = load_predictions(run_path)
    if not predictions or len({item.query_id for item in predictions}) != len(predictions):
        raise ValueError('run이 비어 있거나 query_id가 중복됩니다')
    qrels = load_qrels(qrels_path)
    pairs = frozenset(
        (item.query_id, hit.doc_id)
        for item in predictions
        for hit in (*item.candidates, *item.ranked, *(item.recommended or ()))
    )
    missing = tuple(sorted((qid, did) for qid, did in pairs if did not in qrels.get(qid, {})))
    print(f'Run: {filename}\n비교 pool: {pool_version}\n검사한 쿼리–문서 쌍: {len(pairs):,}')
    print(f'기존 라벨 있음: {len(pairs) - len(missing):,}')
    print(f'신규 라벨 필요: {len(missing):,} ({len({qid for qid, _ in missing})}개 쿼리)')
    if not missing:
        print('추가 라벨링 불필요')
        return None

    corpus_path = DATASET / 'corpus.jsonl'
    queries_path = DATASET / 'queries/eval_queries_80.jsonl'
    inputs = load_inputs(corpus_path, queries_path)
    queries = {query.query_id: query.query for query in inputs.queries}
    documents = {str(doc.id): doc.model_dump(mode='json') for doc in inputs.documents}
    absent = tuple(f'{qid}:{did}' for qid, did in missing if qid not in queries or did not in documents)
    if absent:
        raise ValueError(f'쿼리 또는 공고 원문이 없습니다: {", ".join(absent)}')
    guideline_text = GUIDELINES.read_text(encoding='utf-8')
    guideline_version = re.search(r'^버전 ([\d.]+)', guideline_text, re.MULTILINE)
    reference_date = re.search(r'평가 시간 기준 (\d{4}-\d{2}-\d{2})', guideline_text)
    if guideline_version is None or reference_date is None:
        raise ValueError('라벨링 기준 문서의 버전 또는 평가 기준일을 찾을 수 없습니다')
    rows = tuple({
        'pair_id': f'{qid}:{did}', 'query_id': qid, 'doc_id': did,
        'query': queries[qid], 'document': documents[did],
    } for qid, did in missing)
    sources = (run_path, qrels_path, corpus_path, queries_path, GUIDELINES)
    manifest: dict[str, Any] = {
        'run_id': run_path.stem, 'pool_version': pool_version,
        'pair_count': len(pairs), 'unjudged_count': len(missing),
        'query_count': len({qid for qid, _ in missing}),
        'guideline_file': str(GUIDELINES.relative_to(ROOT)),
        'guideline_version': guideline_version.group(1),
        'reference_date': reference_date.group(1),
        'source_hashes': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sources},
    }
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory = ARTIFACTS / 'labeling_pending' / pool_version / f'{run_path.stem}_{timestamp}'
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'pairs.jsonl').write_text(
        ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8',
    )
    (directory / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
    )
    print(f'저장 위치: {directory}')
    return directory


def main() -> None:
    """run 파일명과 비교 pool 버전을 받아 라벨링 대기 자료를 생성한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('filename', help='runs 폴더의 QueryPrediction JSONL 파일명')
    parser.add_argument('--pool-version', required=True, help='비교할 정답 버전 (예: pool_v1)')
    args = parser.parse_args()
    try:
        find_unjudged(args.filename, args.pool_version)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'오류: {exc}\n')


if __name__ == '__main__':
    main()
