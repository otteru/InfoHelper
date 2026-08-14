-- 사용자가 등록할 공지 사이트 정보를 저장한다.
create table public.sources (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    url text not null,
    created_at timestamp with time zone not null default now(),

    -- constraint는 DB에 들어가는 데이터가 지켜야 하는 규칙(제약조건)
    constraint sources_name_length_check
        check (char_length(btrim(name)) between 1 and 100),

    constraint sources_url_key
        unique (url)
);

-- backend의 service_role만 접근하도록 제한한다.
-- sources 테이블에 RLS(Row Level Security) 를 켜는 거다.
-- RLS와 GRANT/REVOKE는 서로 다른 보안 계층
alter table public.sources
    enable row level security;

-- revoke 권한 회수
revoke all
on table public.sources
from anon, authenticated;

-- service_role - 시스템의 백엔드 서버(FastAPI, Node.js 등)나 관리자가 사용하는 특수 역할
grant select, insert, update, delete
on table public.sources
to service_role;
