"""pool_v1 합본이 3,022쌍이고 기존 산출물을 지우지 않는지 검증한다."""
import json
from pathlib import Path

from RAG_evaluation.labeling import export_pool as module


def test_assemble_covers_full_pool_without_documents() -> None:
    """합본은 pool 3,022쌍이고 공고 원문이 없다."""
    rows = module.assemble()
    assert len(rows) == len({row['pair_id'] for row in rows}) == 3022
    assert {row['pair_id'] for row in rows} == module.pool_ids()
    assert all(row['score'] in (0, 1, 2) for row in rows)
    assert all('document' not in row and 'content' not in row for row in rows)
    sources = {row['source'] for row in rows}
    assert sources == {
        'human_pilot', 'human_holdout', 'human_review', 'assistant_review', 'grok_first_pass',
    }


def test_export_pool_does_not_delete_sources(tmp_path: Path, monkeypatch) -> None:
    """저장 후에도 artifacts와 파일럿 파일이 남아 있다."""
    monkeypatch.setattr(module, 'DESTINATION', tmp_path)
    grok = module.GROK
    original = grok.read_bytes()
    module.main()
    assert (tmp_path / 'judgments.jsonl').exists()
    assert (tmp_path / 'qrels.txt').exists()
    assert grok.read_bytes() == original
    assert module.PILOT.exists()
    assert module.REVIEW.exists()
    assert module.HOLDOUT_LABELS.exists()
