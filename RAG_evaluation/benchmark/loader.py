"""저장된 JSONL 검색 결과를 벤치마크 입력으로 읽는다."""

import json
from itertools import groupby
from pathlib import Path

from RAG_evaluation.benchmark.schema import QueryPrediction

def load_negative_query_ids(path: Path) -> frozenset[str]:
    """쿼리 JSONL에서 no-match로 분류된 쿼리 ID를 읽는다."""
    with path.open(encoding='utf-8-sig') as file:
        rows = tuple(json.loads(line) for line in file if line.strip())
    if any(
        not isinstance(row, dict)
        or any(not isinstance(row.get(key), str) or not row[key].strip() for key in ('query_id', 'type'))
        for row in rows
    ):
        raise ValueError('각 쿼리는 비어 있지 않은 문자열 query_id와 type을 가진 객체여야 합니다')
    if len({row['query_id'].strip() for row in rows}) != len(rows):
        raise ValueError('쿼리 JSONL에 중복 query_id가 있습니다')
    return frozenset(row['query_id'].strip() for row in rows if row['type'].strip() == 'no-match')


def load_qrels(path: Path) -> dict[str, dict[str, int]]:
    """TREC qrels 파일을 쿼리 ID별 문서 정답 점수로 변환한다."""
    rows = tuple(line.split() for line in path.read_text(encoding='utf-8').splitlines() if line.strip())
    if not rows or any(len(row) != 4 or row[3] not in ('0', '1', '2') for row in rows):
        raise ValueError('qrels는 query_id 0 doc_id 점수(0·1·2) 형식이어야 합니다')
    if len({(row[0], row[2]) for row in rows}) != len(rows):
        raise ValueError('qrels에 중복 쿼리·문서 쌍이 있습니다')
    return {
        query_id: {row[2]: int(row[3]) for row in group}
        for query_id, group in groupby(sorted(rows), key=lambda row: row[0])
    }


def load_predictions(path: Path) -> tuple[QueryPrediction, ...]:
    """전달받은 JSONL 파일을 검증해 쿼리별 예측 튜플로 반환한다."""
    with path.open(encoding='utf-8') as file:
        return tuple(
            QueryPrediction.model_validate_json(line)
            for line in file
            if line.strip()
        )
