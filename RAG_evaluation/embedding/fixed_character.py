"""기존 1,000자 청킹 방식의 평가 임베딩과 재개 처리를 제공한다."""

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from openai import OpenAI
from pydantic import BaseModel, ConfigDict
from supabase import Client

from integrations.clients import create_embedding


class Document(BaseModel):
    """평가 corpus의 공고 한 건."""

    model_config = ConfigDict(frozen=True)
    id: UUID
    title: str
    content: str
    url: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class Chunk:
    """공고 식별자와 기존 형식의 임베딩 입력."""

    doc_id: str
    chunk_index: int
    content: str
    embedding_input: str


@dataclass(frozen=True)
class Corpus:
    """파일 해시와 검증한 공고·청크 묶음."""

    sha256: str
    documents: tuple[Document, ...]
    chunks: tuple[Chunk, ...]


def split_text(text: str) -> tuple[str, ...]:
    """기존 ingestion과 동일하게 본문을 겹침 없는 1,000자로 나눈다."""
    return tuple(
        text[index:index + 1000]
        for index in range(0, len(text), 1000)
        if text[index:index + 1000].strip()
    )


def load_corpus(path: Path) -> Corpus:
    """corpus를 읽어 ID·정제 조건을 검증하고 전체 청크를 생성한다."""
    raw = path.read_bytes()
    documents = tuple(
        Document.model_validate_json(line)
        for line in raw.decode('utf-8').splitlines() if line.strip()
    )
    if not documents or len({doc.id for doc in documents}) != len(documents):
        raise ValueError('corpus가 비어 있거나 중복 ID가 있습니다')
    if any(len(doc.content.strip()) < 50 for doc in documents):
        raise ValueError('본문 50자 미만 공고가 있습니다')
    if len({(doc.title, doc.content) for doc in documents}) != len(documents):
        raise ValueError('제목과 본문이 동일한 공고가 있습니다')
    chunks = tuple(
        Chunk(str(doc.id), index, text, f'title: {doc.title} | text: {text}')
        for doc in documents
        for index, text in enumerate(split_text(doc.content))
    )
    return Corpus(hashlib.sha256(raw).hexdigest(), documents, chunks)


def run_payload(
    corpus: Corpus, name: str, version: str, model: str, dimensions: int,
) -> dict[str, Any]:
    """재실행 시에도 동일하게 비교할 실험 설정을 생성한다."""
    if not name or not version or not model or not 1 <= dimensions <= 16000:
        raise ValueError('이름·버전·모델과 유효한 차원(1~16000)이 필요합니다')
    return {
        'name': name, 'corpus_version': version, 'corpus_sha256': corpus.sha256,
        'embedding_model': model, 'dimensions': dimensions,
        'expected_documents': len(corpus.documents), 'expected_chunks': len(corpus.chunks),
        'config': {
            'implementation_version': 1,
            'chunking': {'method': 'fixed_character', 'size': 1000, 'overlap': 0},
            'provider': 'openrouter',
            'document_template': 'title: {title} | text: {chunk}',
            'query_template': 'text: {query}',
        },
    }


def select_rows(
    db: Client, table: str, column: str, value: str, fields: str, order: str,
) -> tuple[dict[str, Any], ...]:
    """Supabase의 응답 행 제한을 고려해 정렬된 페이지를 모두 조회한다."""
    rows: tuple[dict[str, Any], ...] = ()
    while True:
        page = db.table(table).select(fields).eq(column, value).order(order).range(
            len(rows), len(rows) + 499,
        ).execute().data
        rows = (*rows, *page)
        if len(page) < 500:
            return rows


def ensure_run(db: Client, payload: dict[str, Any]) -> dict[str, Any]:
    """동일 이름의 실험을 재사용하되 설정이 다르면 중단한다."""
    rows = db.table('eval_embedding_runs').select('*').eq('name', payload['name']).execute().data
    if rows:
        row = rows[0]
        if any(row[key] != value for key, value in payload.items()):
            raise ValueError('기존 run 설정과 다릅니다. 새 run 이름을 사용하세요')
        return row
    return db.table('eval_embedding_runs').insert(payload).execute().data[0]


def save_documents(db: Client, corpus: Corpus, version: str) -> None:
    """저장된 원본과 내용이 같은지 확인하고 누락된 공고만 등록한다."""
    expected = {
        str(doc.id): {'corpus_version': version, 'doc_id': str(doc.id),
                     **doc.model_dump(mode='json', exclude={'id'})}
        for doc in corpus.documents
    }
    existing = select_rows(db, 'eval_documents', 'corpus_version', version, '*', 'doc_id')
    if any(expected.get(row['doc_id']) != row for row in existing):
        raise ValueError('동일 corpus_version에 다른 공고 내용이 저장되어 있습니다')
    saved = frozenset(row['doc_id'] for row in existing)
    missing = tuple(row for doc_id, row in expected.items() if doc_id not in saved)
    for offset in range(0, len(missing), 100):
        db.table('eval_documents').insert(list(missing[offset:offset + 100])).execute()
    count = db.table('eval_documents').select('doc_id', count='exact', head=True).eq(
        'corpus_version', version,
    ).execute().count
    if count != len(corpus.documents):
        raise ValueError('등록된 문서 수가 corpus와 다릅니다')


def saved_chunk_keys(db: Client, corpus: Corpus, run_id: str) -> frozenset[tuple[str, int]]:
    """저장된 청크 내용이 일치하는지 확인하고 완료 식별자를 반환한다."""
    expected = {(chunk.doc_id, chunk.chunk_index): chunk for chunk in corpus.chunks}
    rows = select_rows(
        db, 'eval_chunks', 'run_id', run_id,
        'doc_id,chunk_index,content,embedding_input', 'doc_id,chunk_index',
    )
    for row in rows:
        chunk = expected.get((row['doc_id'], row['chunk_index']))
        if chunk is None or (chunk.content, chunk.embedding_input) != (
            row['content'], row['embedding_input'],
        ):
            raise ValueError('저장된 청크가 현재 실험 입력과 다릅니다')
    return frozenset((row['doc_id'], row['chunk_index']) for row in rows)


def validate_embedding(values: list[float], dimensions: int) -> None:
    """벡터 차원·유한값·영벡터 여부를 DB 저장 전에 검사한다."""
    if len(values) != dimensions or not all(math.isfinite(value) for value in values):
        raise ValueError('임베딩 응답의 차원 또는 숫자 값이 올바르지 않습니다')
    if not any(values):
        raise ValueError('코사인 검색에 사용할 수 없는 영벡터입니다')


def embed_batch(
    client: OpenAI, chunks: tuple[Chunk, ...], model: str, dimensions: int,
) -> tuple[list[float], ...]:
    """동일한 입력 형식으로 요청을 묶고 응답 index에 따라 원래 순서를 복원한다."""
    if len(chunks) == 1:
        vectors = (create_embedding(client, chunks[0].embedding_input, model=model, dimensions=dimensions),)
    else:
        response = client.embeddings.create(
            model=model, dimensions=dimensions,
            input=[chunk.embedding_input for chunk in chunks],
        )
        if sorted(item.index for item in response.data) != list(range(len(chunks))):
            raise ValueError('임베딩 응답 index 또는 개수가 입력과 다릅니다')
        vectors = tuple(item.embedding for item in sorted(response.data, key=lambda item: item.index))
    for values in vectors:
        validate_embedding(values, dimensions)
    return vectors


def execute_run(
    db: Client, client: OpenAI, corpus: Corpus, payload: dict[str, Any],
    limit_documents: int | None = None, resume_running: bool = False, batch_size: int = 1,
) -> dict[str, Any]:
    """원본 등록 후 누락 청크를 임베딩하고 전체 저장 완료 여부를 기록한다."""
    if batch_size <= 0 or (limit_documents is not None and limit_documents <= 0):
        raise ValueError('배치 크기와 문서 제한은 양수여야 합니다')
    run = ensure_run(db, payload)
    run_id = run['run_id']
    if run['status'] == 'running' and not resume_running:
        raise ValueError('실행 중인 run입니다. 이전 프로세스 종료 확인 후 --resume-running을 사용하세요')
    if run['status'] == 'completed':
        save_documents(db, corpus, payload['corpus_version'])
        if len(saved_chunk_keys(db, corpus, run_id)) != len(corpus.chunks):
            raise ValueError('완료 run의 청크 수가 다릅니다')
        return {'run_id': run_id, 'status': 'completed', 'new_embeddings': 0}
    claimed = db.table('eval_embedding_runs').update({'status': 'running'}).eq(
        'run_id', run_id,
    ).eq('status', run['status']).execute().data
    if not claimed:
        raise ValueError('다른 프로세스가 run 상태를 변경했습니다')
    try:
        save_documents(db, corpus, payload['corpus_version'])
        saved = saved_chunk_keys(db, corpus, run_id)
        selected = frozenset(str(doc.id) for doc in corpus.documents[:limit_documents])
        pending = tuple(chunk for chunk in corpus.chunks if chunk.doc_id in selected
                        and (chunk.doc_id, chunk.chunk_index) not in saved)
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset:offset + batch_size]
            vectors = embed_batch(client, batch, payload['embedding_model'], payload['dimensions'])
            db.table('eval_chunks').insert([{
                'run_id': run_id, 'corpus_version': payload['corpus_version'],
                'doc_id': chunk.doc_id, 'chunk_index': chunk.chunk_index,
                'content': chunk.content, 'embedding_input': chunk.embedding_input,
                'dimensions': payload['dimensions'], 'embedding': values,
            } for chunk, values in zip(batch, vectors, strict=True)]).execute()
            print(json.dumps({'saved_this_execution': offset + len(batch), 'planned': len(pending)}), flush=True)
        total = len(saved_chunk_keys(db, corpus, run_id))
        status = 'completed' if total == len(corpus.chunks) else 'pending'
        db.table('eval_embedding_runs').update({'status': status}).eq('run_id', run_id).execute()
        return {'run_id': run_id, 'status': status, 'new_embeddings': len(pending),
                'saved_chunks': total, 'expected_chunks': len(corpus.chunks)}
    except BaseException as error:
        try:
            db.table('eval_embedding_runs').update({'status': 'failed'}).eq('run_id', run_id).execute()
        except Exception:
            error.add_note('실패 상태 기록도 실패했습니다. DB 연결 복구 후 run 상태를 확인하세요.')
        raise
