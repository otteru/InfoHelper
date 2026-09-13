-- 공고별 최대 점수와 다른 차원 run의 격리를 검증한 뒤 롤백한다.
begin;
set local role service_role;
insert into public.eval_documents
select '__dense_test__', ('00000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid,
       '제목', '본문', 'https://example.com', '{}'::jsonb from generate_series(1, 3) i;
insert into public.eval_embedding_runs
    (run_id, name, corpus_version, corpus_sha256, embedding_model, dimensions, config, expected_documents, expected_chunks)
values
('00000000-0000-0000-0001-000000000001', '__dense_test_2__', '__dense_test__', repeat('c',64), 'test', 2, '{}', 3, 4),
('00000000-0000-0000-0001-000000000002', '__dense_test_3__', '__dense_test__', repeat('c',64), 'test', 3, '{}', 3, 1);
insert into public.eval_chunks values
('00000000-0000-0000-0001-000000000001', '__dense_test__', '00000000-0000-0000-0000-000000000001', 0, '본문', '입력', 2, '[1,0]'),
('00000000-0000-0000-0001-000000000001', '__dense_test__', '00000000-0000-0000-0000-000000000001', 1, '본문', '입력', 2, '[0.99,0.01]'),
('00000000-0000-0000-0001-000000000001', '__dense_test__', '00000000-0000-0000-0000-000000000002', 0, '본문', '입력', 2, '[0.8,0.6]'),
('00000000-0000-0000-0001-000000000001', '__dense_test__', '00000000-0000-0000-0000-000000000003', 0, '본문', '입력', 2, '[0,1]'),
('00000000-0000-0000-0001-000000000002', '__dense_test__', '00000000-0000-0000-0000-000000000003', 0, '본문', '입력', 3, '[1,0,0]');
update public.eval_embedding_runs set status = 'completed' where corpus_version = '__dense_test__';
do $$
declare
    ids uuid[];
    rejected boolean := false;
begin
    select array_agg(doc_id order by score desc) into ids
    from public.match_eval_documents('00000000-0000-0000-0001-000000000001', '[1,0]', 2);
    if ids <> array['00000000-0000-0000-0000-000000000001'::uuid,
                    '00000000-0000-0000-0000-000000000002'::uuid] then
        raise exception '공고별 최고 점수 또는 run 격리 검증 실패';
    end if;
    begin
        perform * from public.match_eval_documents('00000000-0000-0000-0001-000000000001', '[1,0,0]', 2);
    exception when raise_exception then rejected := true;
    end;
    if not rejected then raise exception '잘못된 쿼리 차원을 허용했습니다'; end if;
    rejected := false;
    update public.eval_embedding_runs set status = 'pending' where name = '__dense_test_2__';
    begin
        perform * from public.match_eval_documents('00000000-0000-0000-0001-000000000001', '[1,0]', 2);
    exception when raise_exception then rejected := true;
    end;
    if not rejected then raise exception '미완료 run 검색을 허용했습니다'; end if;
    if has_function_privilege('anon', 'public.match_eval_documents(uuid,extensions.vector,integer)', 'execute')
       or has_function_privilege('authenticated', 'public.match_eval_documents(uuid,extensions.vector,integer)', 'execute') then
        raise exception '검색 함수가 공개되어 있습니다';
    end if;
end;
$$;
rollback;
