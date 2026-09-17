-- 평가 원본과 실험별 벡터를 운영 데이터에서 분리한다.
create table public.eval_documents (
    corpus_version text not null check (length(corpus_version) > 0),
    doc_id uuid not null,
    title text not null,
    content text not null,
    url text not null,
    metadata jsonb not null check (jsonb_typeof(metadata) = 'object'),
    primary key (corpus_version, doc_id)
);

create table public.eval_embedding_runs (
    run_id uuid primary key default gen_random_uuid(),
    name text not null unique check (length(name) > 0),
    corpus_version text not null,
    corpus_sha256 text not null check (corpus_sha256 ~ '^[0-9a-f]{64}$'),
    embedding_model text not null,
    dimensions integer not null check (dimensions between 1 and 16000),
    config jsonb not null check (jsonb_typeof(config) = 'object'),
    expected_documents integer not null check (expected_documents > 0),
    expected_chunks integer not null check (expected_chunks > 0),
    status text not null default 'pending'
        check (status in ('pending', 'running', 'completed', 'failed')),
    created_at timestamptz not null default now(),
    unique (run_id, corpus_version, dimensions)
);

create table public.eval_chunks (
    run_id uuid not null,
    corpus_version text not null,
    doc_id uuid not null,
    chunk_index integer not null check (chunk_index >= 0),
    content text not null check (length(btrim(content)) > 0),
    embedding_input text not null,
    dimensions integer not null,
    embedding extensions.vector not null,
    primary key (run_id, doc_id, chunk_index),
    foreign key (corpus_version, doc_id)
        references public.eval_documents (corpus_version, doc_id),
    foreign key (run_id, corpus_version, dimensions)
        references public.eval_embedding_runs (run_id, corpus_version, dimensions),
    check (extensions.vector_dims(embedding) = dimensions),
    check (extensions.vector_norm(embedding) > 0)
);

-- 같은 corpus 버전에 다른 파일을 등록하거나 기존 실험 설정을 바꾸지 못하게 한다.
create function public.guard_eval_embedding_run()
returns trigger language plpgsql set search_path = '' as $$
begin
    if TG_OP = 'INSERT' then
        perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(new.corpus_version, 0));
        if exists (
            select 1 from public.eval_embedding_runs
            where corpus_version = new.corpus_version
              and (corpus_sha256 <> new.corpus_sha256
                   or expected_documents <> new.expected_documents)
        ) then
            raise exception '동일 corpus_version의 파일 해시 또는 문서 수가 다릅니다';
        end if;
    elsif (to_jsonb(new) - 'status') is distinct from (to_jsonb(old) - 'status') then
        raise exception '기존 run 설정은 변경할 수 없습니다';
    end if;

    if new.status = 'completed' then
        if (select count(*) from public.eval_documents where corpus_version = new.corpus_version)
                <> new.expected_documents
           or (select count(*) from public.eval_chunks where run_id = new.run_id)
                <> new.expected_chunks then
            raise exception '문서 또는 청크 수가 예상 수와 다릅니다';
        end if;
    end if;
    return new;
end;
$$;

create trigger guard_eval_embedding_run
before insert or update on public.eval_embedding_runs
for each row execute function public.guard_eval_embedding_run();

alter table public.eval_documents enable row level security;
alter table public.eval_embedding_runs enable row level security;
alter table public.eval_chunks enable row level security;
revoke all on public.eval_documents, public.eval_embedding_runs, public.eval_chunks
    from public, anon, authenticated, service_role;
grant select, insert on public.eval_documents, public.eval_chunks to service_role;
grant select, insert on public.eval_embedding_runs to service_role;
grant update (status) on public.eval_embedding_runs to service_role;
revoke all on function public.guard_eval_embedding_run() from public, anon, authenticated;
grant execute on function public.guard_eval_embedding_run() to service_role;
