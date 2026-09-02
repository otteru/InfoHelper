-- 공지 상세 페이지의 제목과 본문 추출 규칙을 선택적으로 저장한다.
alter table public.source_crawl_rules
add column detail_rule_definition jsonb;

alter table public.source_crawl_rules
add constraint source_crawl_rules_detail_rule_definition_object_check
check (
    detail_rule_definition is null
    or jsonb_typeof(detail_rule_definition) = 'object'
);
