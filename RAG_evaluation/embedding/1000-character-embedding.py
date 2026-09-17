"""기존 1,000자 청킹 방식으로 평가 corpus를 임베딩하는 실행 진입점."""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

# 파일 직접 실행에서도 프로젝트의 공통 클라이언트를 불러온다.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from RAG_evaluation.embedding.fixed_character import execute_run, load_corpus, run_payload
from integrations.clients import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    create_openrouter_client,
    create_supabase_client,
)


def main() -> None:
    """실험 옵션을 읽고 dry-run 또는 재개 가능한 임베딩을 실행한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=ROOT / 'RAG_evaluation/dataset/corpus.jsonl')
    parser.add_argument('--corpus-version', default='zighang_v1')
    parser.add_argument('--run-name', default='fixed1000_qwen1536_v1')
    parser.add_argument('--model', default=EMBEDDING_MODEL)
    parser.add_argument('--dimensions', type=int, default=EMBEDDING_DIMENSIONS)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env.local')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--limit-documents', type=int)
    parser.add_argument('--resume-running', action='store_true')
    parser.add_argument('--batch-size', type=int, default=1)
    args = parser.parse_args()
    if args.limit_documents is not None and args.limit_documents <= 0:
        parser.error('--limit-documents는 양수여야 합니다')
    if args.batch_size <= 0:
        parser.error('--batch-size는 양수여야 합니다')
    corpus = load_corpus(args.corpus)
    payload = run_payload(corpus, args.run_name, args.corpus_version, args.model, args.dimensions)
    print(json.dumps({**payload, 'sample_input': corpus.chunks[0].embedding_input}, ensure_ascii=False), flush=True)
    if args.dry_run:
        return
    if not args.env_file.is_file():
        parser.error(f'환경 파일이 없습니다: {args.env_file}')
    load_dotenv(ROOT / '.env')
    load_dotenv(args.env_file, override=True)
    result = execute_run(
        create_supabase_client(), create_openrouter_client(), corpus, payload,
        args.limit_documents, args.resume_running, args.batch_size,
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
