-- baseline에 포함된 공개 권한을 제거하고 backend 전용 접근 구조로 변경한다.
-- 기존 객체의 권한과 앞으로 생성될 객체의 기본 권한을 함께 제한한다.

-- 앞으로 생성되는 객체에 공개 권한을 자동 부여하지 않는다.
alter default privileges
for role postgres
in schema public
revoke all on tables from anon, authenticated;

alter default privileges
for role postgres
in schema public
revoke all on sequences from anon, authenticated;

alter default privileges
for role postgres
in schema public
revoke all on routines from anon, authenticated;


-- 기존 테이블 권한을 제거한다.
revoke all
on table public.notice_chunks
from anon, authenticated;

revoke all
on table public.recommendation_deliveries
from anon, authenticated;


-- 기존 Sequence 권한을 제거한다.
revoke all
on sequence public.notice_chunks_id_seq
from anon, authenticated;


-- 기존 RPC 실행 권한을 제거한다.
revoke all
on function public.match_notice_chunks(extensions.vector, integer)
from public, anon, authenticated;

revoke all
on function public.find_delivered_pairs(jsonb)
from public, anon, authenticated;


-- backend에 필요한 권한을 유지한다.
grant select, insert, update, delete
on table public.notice_chunks
to service_role;

grant select, insert
on table public.recommendation_deliveries
to service_role;

grant usage, select
on sequence public.notice_chunks_id_seq
to service_role;

grant execute
on function public.match_notice_chunks(extensions.vector, integer)
to service_role;

grant execute
on function public.find_delivered_pairs(jsonb)
to service_role;
