"""평가 결과를 AI 호출 없이 JSON과 Markdown 보고서로 저장한다."""

import re
from datetime import datetime, timezone
from pathlib import Path

from RAG_evaluation.benchmark.schema import BenchmarkReport, SystemMetrics


def _format(value: float | None, missing: str = '계산 불가', digits: int = 4) -> str:
    """점수의 표시 정밀도와 누락 상태를 구분한다."""
    return missing if value is None else f'{value:.{digits}f}'


def _escape(value: str) -> str:
    """Markdown 표의 구분 문자와 줄바꿈을 이스케이프한다."""
    return value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('|', '&#124;').replace('\n', ' ').replace('\r', ' ').replace('`', '&#96;')


def _latency_kind_label(system: SystemMetrics | None) -> str:
    """보고서 표에 쓸 지연시간 산출 방식 이름을 반환한다."""
    if system is None or system.latency_kind is None:
        return '미측정'
    return {'measured': '실측', 'estimated': '추정'}[system.latency_kind]


def render_markdown(report: BenchmarkReport) -> str:
    """고정 템플릿에 집계 결과와 하위 10개 쿼리 결과를 채운다."""
    recommendation, system = report.recommendation, report.system
    rows = (
        ('Candidate Retrieval', 'Primary', 'Recall@20', _format(report.candidate.recall_at_20)),
        ('Candidate Retrieval', 'Secondary', 'Success@20', _format(report.candidate.success_at_20)),
        ('Ranking', 'Primary', 'nDCG@5', _format(report.ranking.ndcg_at_5)),
        ('Ranking', 'Secondary', 'Precision@5', _format(report.ranking.precision_at_5)),
        ('Ranking', 'Secondary', 'MRR@5', _format(report.ranking.mrr_at_5)),
        ('Recommendation Decision', 'Primary', 'Precision', _format(recommendation.precision) if recommendation else '미실행'),
        ('Recommendation Decision', 'Secondary', 'Recall', _format(recommendation.recall) if recommendation else '미실행'),
        ('Recommendation Decision', 'Secondary', 'Negative-query accuracy', _format(recommendation.negative_query_accuracy) if recommendation else '미실행'),
        ('System / Serving', 'Primary', f'p95 latency (ms, {_latency_kind_label(system)})', _format(system.p95_latency_ms, '미측정') if system else '미측정'),
        ('System / Serving', 'Secondary', f'p50 latency (ms, {_latency_kind_label(system)})', _format(system.p50_latency_ms, '미측정') if system else '미측정'),
        ('System / Serving', 'Secondary', 'cost/query (USD)', _format(system.mean_cost_usd_per_query, '미측정', 8) if system else '미측정'),
    )
    lowest = sorted(
        (item for item in report.per_query if item.ranking.ndcg_at_5 is not None),
        key=lambda item: (item.ranking.ndcg_at_5, item.query_id),
    )[:10]
    return '\n'.join((
        '# 검색 평가 보고서', '', '## 평가 정보', '',
        '| 항목 | 값 |', '|---|---|',
        f'| Run | {_escape(report.run_id)} |',
        f'| 정답 버전 | {_escape(report.qrels_version)} |',
        f'| 쿼리 수 | {report.query_count} |',
        '| 관련 문서 기준 | qrel >= 1 |',
        '| 추천 정답 기준 | qrel == 2 |',
        '| nDCG gain | 2^grade - 1 |',
        '| 집계 방식 | 쿼리별 macro 평균, None 제외 |',
        f'| Recall@20 유효 쿼리 | {sum(item.candidate.recall_at_20 is not None for item in report.per_query)} |',
        f'| nDCG@5 유효 쿼리 | {sum(item.ranking.ndcg_at_5 is not None for item in report.per_query)} |',
        f'| 평가된 negative query | {recommendation.negative_query_count if recommendation else 0} |',
        f'| 시간 측정 방식 | {_latency_kind_label(system)} |',
        f'| 시간 측정 표본 | {system.latency_sample_count if system else 0} |',
        f'| 비용 측정 표본 | {system.cost_sample_count if system else 0} |',
        '', '## 평가 결과', '',
        '| Stage | 구분 | 지표 | 결과 |', '|---|---|---|---:|',
        *('|' + ' | '.join(row) + ' |' for row in rows),
        '', '## 낮은 nDCG@5 쿼리', '',
        '계산 가능한 쿼리 중 낮은 점수 순으로 최대 10개를 표시하며 동점은 Query ID 순이다.', '',
        '| Query ID | Recall@20 | nDCG@5 | Precision@5 | MRR@5 |',
        '|---|---:|---:|---:|---:|',
        *(f'| {_escape(item.query_id)} | {_format(item.candidate.recall_at_20)} | {_format(item.ranking.ndcg_at_5)} | {_format(item.ranking.precision_at_5)} | {_format(item.ranking.mrr_at_5)} |' for item in lowest),
        *(() if lowest else ('', '표시할 유효 쿼리가 없습니다.')),
        '', '## 평가 시 유의사항', '',
        '- Recall은 라벨링된 pool 기준이며 전체 corpus의 Recall을 보장하지 않는다.',
        '- pool_v1은 사람·자동 라벨이 혼합된 정답이다.',
        '- 미평가 문서가 검색 결과에 포함되면 평가를 중단한다.',
        '- 분모가 0인 Recall·nDCG·추천 Precision은 계산 불가이며 평균에서 제외한다.',
        '- Precision@5는 반환 문서가 부족해도 분모 5를 사용한다.',
        '- 추천 결과가 있는 쿼리만 추천 지표에 포함한다.',
        '- negative query는 별도 지정하며 해당 qrels는 모두 0점이어야 한다.',
        '- 지연시간은 kind가 있는 total_ms의 선형 보간 백분위수이며 실측과 추정을 섞지 않는다. 비용은 측정된 값의 평균이다.',
        '- 미실행·미측정·계산 불가는 실제 0점과 다르다.', '',
    ))


def save_report(report: BenchmarkReport, output_dir: Path) -> Path:
    """정답 버전 아래 실행별 폴더에 JSON과 Markdown 보고서를 저장한다."""
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', report.run_id):
        raise ValueError('run_id는 영문·숫자·밑줄·하이픈만 사용할 수 있습니다')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', report.qrels_version):
        raise ValueError('qrels_version은 영문·숫자·밑줄·하이픈만 사용할 수 있습니다')
    json_content = report.model_dump_json(indent=2) + '\n'
    markdown_content = render_markdown(report)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory = output_dir / report.qrels_version / f'{report.run_id}_{timestamp}'
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'result.json').write_text(json_content, encoding='utf-8')
    (directory / 'report.md').write_text(markdown_content, encoding='utf-8')
    return directory
