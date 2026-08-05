-- 앞으로 postgres 역할이 public 스키마에 생성하는 함수가 PUBLIC에 자동 공개되지 않도록 한다.
-- 필요한 RPC는 생성 migration에서 service_role에만 실행 권한을 명시적으로 부여해야 한다.
alter default privileges
for role postgres
in schema public
revoke execute on routines from public;
