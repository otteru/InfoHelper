-- 목록과 상세 페이지의 렌더링 전략을 활성 크롤링 규칙 버전과 함께 보관한다.
alter table public.source_crawl_rules
add column list_crawl_mode text not null default 'default',
add column detail_crawl_mode text not null default 'default',
add constraint source_crawl_rules_list_crawl_mode_check
    check (list_crawl_mode in ('default', 'dynamic', 'infinite_scroll')),
add constraint source_crawl_rules_detail_crawl_mode_check
    check (detail_crawl_mode in ('default', 'dynamic', 'infinite_scroll'));
