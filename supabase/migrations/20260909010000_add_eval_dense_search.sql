-- 완료된 한 실험에서 모든 청크를 정확 검색한 뒤 공고별 최고 점수를 반환한다.
create function public.match_eval_documents(
    p_run_id uuid,
    p_query_embedding extensions.vector,
    p_top_k integer default 20
)
returns table (doc_id uuid, score double precision)
language plpgsql stable set search_path = '' as $$
declare
    selected_run public.eval_embedding_runs%rowtype;
begin
    if p_top_k is null or p_top_k < 1 or p_top_k > 1000 then
        raise exception 'top_k는 1~1000이어야 합니다';
    end if;
    select * into selected_run from public.eval_embedding_runs where run_id = p_run_id;
    if not found or selected_run.status <> 'completed' then
        raise exception '완료된 embedding run이 필요합니다';
    end if;
    if p_query_embedding is null
       or extensions.vector_dims(p_query_embedding) <> selected_run.dimensions
       or extensions.vector_norm(p_query_embedding) = 0 then
        raise exception '쿼리 벡터 차원 또는 크기가 올바르지 않습니다';
    end if;
    return query
    with candidates as materialized (
        select c.doc_id, c.embedding
        from public.eval_chunks c where c.run_id = p_run_id
    )
    select c.doc_id, max(1 - (c.embedding operator(extensions.<=>) p_query_embedding)) as score
    from candidates c
    group by c.doc_id
    order by score desc, c.doc_id asc
    limit p_top_k;
end;
$$;

revoke all on function public.match_eval_documents(uuid, extensions.vector, integer)
    from public, anon, authenticated;
grant execute on function public.match_eval_documents(uuid, extensions.vector, integer)
    to service_role;
