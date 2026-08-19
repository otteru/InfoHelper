-- 사이트별 크롤링 규칙과 규칙의 검증·운영 상태를 저장한다.
create table public.source_crawl_rules (
    id uuid primary key default gen_random_uuid(),
    source_id uuid not null,
    -- version - 크롤링 규칙, rule_schema_version - json의 형식 버전
    version integer not null,
    rule_schema_version smallint not null default 1,
    status text not null default 'candidate',
    validation_status text not null default 'pending',
    health_status text,
    rule_definition jsonb not null,
    generated_by text not null,
    created_at timestamp with time zone not null default now(),
    validated_at timestamp with time zone,
    last_health_checked_at timestamp with time zone,

    constraint source_crawl_rules_source_id_fkey
        foreign key (source_id)
        references public.sources (id)
        -- source에서 삭제되면 같이 삭제되도록
        on delete cascade,

    constraint source_crawl_rules_source_id_version_key
        unique (source_id, version),

    constraint source_crawl_rules_version_check
        check (version > 0),

    constraint source_crawl_rules_rule_schema_version_check
        check (rule_schema_version > 0),

    -- status -> "지금 운영에 투입된 규칙인가?"
    constraint source_crawl_rules_status_check
        check (status in ('candidate', 'active', 'retired', 'rejected')),

    constraint source_crawl_rules_validation_status_check
        check (validation_status in ('pending', 'passed', 'failed')),

    -- health_stauts - "실제 운영 중인데 지금도 잘 되는가?"
    constraint source_crawl_rules_health_status_check
        check (
            (
                status = 'active'
                and health_status is not null
                and health_status in ('unknown', 'healthy', 'degraded', 'broken')
            )
            or (
                status <> 'active'
                and health_status is null
            )
        ),

    constraint source_crawl_rules_rule_definition_object_check
        check (jsonb_typeof(rule_definition) = 'object'),

    constraint source_crawl_rules_generated_by_check
        check (generated_by in ('legacy', 'manual', 'llm'))
);

-- 하나의 사이트에는 활성 규칙을 하나만 허용한다.
create unique index source_crawl_rules_one_active_per_source_idx
on public.source_crawl_rules (source_id)
where status = 'active';

-- backend의 service_role만 접근하도록 제한한다.
alter table public.source_crawl_rules
    enable row level security;

revoke all
on table public.source_crawl_rules
from anon, authenticated;

grant select, insert, update, delete
on table public.source_crawl_rules
to service_role;
