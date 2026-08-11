-- 추천 코드가 필수 문자열로 사용하는 공지 식별자·제목·URL의 NULL 저장을 차단한다.
-- 적용 전 원격 테이블에 해당 컬럼의 NULL 데이터가 없는지 확인했다.
alter table public.notice_chunks
    alter column notice_id set not null,
    alter column title set not null,
    alter column url set not null;
