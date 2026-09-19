"""벤치마크 실행 진입점."""

import argparse
from pathlib import Path

from RAG_evaluation.benchmark.evaluator import evaluate
from RAG_evaluation.benchmark.loader import load_negative_query_ids, load_predictions, load_qrels
from RAG_evaluation.benchmark.report import save_report

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / 'artifacts' / 'zighang_v1' / 'runs'
QRELS_PATH = ROOT / 'dataset' / 'labeling' / 'pool_v1' / 'qrels.txt'
QUERIES_PATH = ROOT / 'dataset' / 'queries' / 'eval_queries_80.jsonl'
REPORTS_DIR = ROOT / 'artifacts' / 'zighang_v1' / 'benchmark_reports'


def main() -> None:
    """검색 결과와 정답을 불러와 벤치마크 평가를 실행한다."""
    parser = argparse.ArgumentParser(description='검색 결과 벤치마크')
    parser.add_argument('filename', help='runs 폴더 안의 JSONL 파일명')
    args = parser.parse_args()

    if not args.filename or Path(args.filename).name != args.filename or Path(args.filename).suffix != '.jsonl':
        parser.error('경로 없이 .jsonl 파일명만 입력하세요')

    run_path = RUNS_DIR / args.filename
    predictions = load_predictions(run_path)
    qrels = load_qrels(QRELS_PATH)
    negative_query_ids = load_negative_query_ids(QUERIES_PATH)
    report = evaluate(
        predictions,
        qrels,
        run_id=run_path.stem,
        qrels_version=QRELS_PATH.parent.name,
        negative_query_ids=negative_query_ids,
    )
    print(report.model_dump_json(indent=2, exclude={'per_query'}))
    report_dir = save_report(report, REPORTS_DIR)
    print(f'보고서 저장 완료: {report_dir}')


if __name__ == '__main__':
    main()
