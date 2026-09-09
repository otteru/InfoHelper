-- 테스트 데이터와 변경 사항은 마지막에 전부 롤백한다.
begin;
set local role service_role;

insert into public.eval_documents values
('__schema_test__', '00000000-0000-0000-0000-000000000001', '제목', '본문', 'https://example.com', '{}');
insert into public.eval_embedding_runs
    (run_id, name, corpus_version, corpus_sha256, embedding_model, dimensions, config,
     expected_documents, expected_chunks)
values
('00000000-0000-0000-0000-000000000002', '__schema_test_2__', '__schema_test__', repeat('a', 64), 'test', 2, '{}', 1, 1),
('00000000-0000-0000-0000-000000000003', '__schema_test_3__', '__schema_test__', repeat('a', 64), 'test', 3, '{}', 1, 1);

do $$
declare rejected boolean := false;
begin
    begin
        insert into public.eval_embedding_runs
            (name, corpus_version, corpus_sha256, embedding_model, dimensions, config,
             expected_documents, expected_chunks)
        values ('__schema_bad_hash__', '__schema_test__', repeat('b', 64), 'test', 2, '{}', 1, 1);
    exception when raise_exception then rejected := true;
    end;
    if not rejected then raise exception '파일 해시 변경 차단 실패'; end if;

    rejected := false;
    begin
        update public.eval_embedding_runs set status = 'completed'
        where name = '__schema_test_2__';
    exception when raise_exception then rejected := true;
    end;
    if not rejected then raise exception '부분 완료 차단 실패'; end if;

    begin
        insert into public.eval_chunks values
        ('00000000-0000-0000-0000-000000000002', '__schema_test__',
         '00000000-0000-0000-0000-000000000001', 0, '본문', '입력', 2, '[1,0,0]');
        raise exception '벡터 차원 검사 실패';
    exception when check_violation then null;
    end;

    begin
        insert into public.eval_chunks values
        ('00000000-0000-0000-0000-000000000002', '__schema_test__',
         '00000000-0000-0000-0000-000000000001', 0, '본문', '입력', 3, '[1,0,0]');
        raise exception 'run 차원 외래키 검사 실패';
    exception when foreign_key_violation then null;
    end;

    begin
        insert into public.eval_chunks values
        ('00000000-0000-0000-0000-000000000002', '__other_corpus__',
         '00000000-0000-0000-0000-000000000001', 0, '본문', '입력', 2, '[1,0]');
        raise exception 'corpus 외래키 검사 실패';
    exception when foreign_key_violation then null;
    end;

    if has_table_privilege('anon', 'public.eval_documents', 'SELECT')
       or has_table_privilege('authenticated', 'public.eval_chunks', 'INSERT')
       or has_column_privilege('service_role', 'public.eval_embedding_runs', 'config', 'UPDATE') then
        raise exception '서버 전용 또는 설정 불변 권한 검사 실패';
    end if;
end;
$$;

insert into public.eval_chunks values
('00000000-0000-0000-0000-000000000002', '__schema_test__',
 '00000000-0000-0000-0000-000000000001', 0, '본문', '입력', 2, '[1,0]'),
('00000000-0000-0000-0000-000000000003', '__schema_test__',
 '00000000-0000-0000-0000-000000000001', 0, '본문', '입력', 3, '[1,0,0]');
update public.eval_embedding_runs set status = 'completed'
where name in ('__schema_test_2__', '__schema_test_3__');
rollback;
