-- Migration unit 1: schema_changes
-- Transaction mode: transactional
-- Boundary reason: default
-- 기존 원격 Supabase DB의 구조를 처음으로 버전 관리하기 위한 기준 migration이다.
-- 당시의 권한 설정도 그대로 포함하며, 과도한 공개 권한은 후속 migration에서 제거한다.

SET check_function_bodies = false;

CREATE EXTENSION vector WITH SCHEMA extensions;

-- 원격 DB를 가져온 시점의 기본 권한이다.
-- anon/authenticated 기본 권한은 restrict_backend_permissions migration에서 제거한다.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT DELETE, INSERT, SELECT, UPDATE ON TABLES TO anon;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT, USAGE ON SEQUENCES TO anon;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON ROUTINES TO anon;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT DELETE, INSERT, SELECT, UPDATE ON TABLES TO authenticated;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT, USAGE ON SEQUENCES TO authenticated;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON ROUTINES TO authenticated;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT DELETE, INSERT, SELECT, UPDATE ON TABLES TO service_role;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT, USAGE ON SEQUENCES TO service_role;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON ROUTINES TO service_role;

CREATE SEQUENCE public.notice_chunks_id_seq;

-- 발송 후보 중 이미 발송 이력이 존재하는 조합만 반환한다.
CREATE FUNCTION public.find_delivered_pairs (
  p_candidates jsonb
)
  RETURNS TABLE (
    recipient_email text,
    notice_id       text,
    channel         text
  )
  LANGUAGE sql
  STABLE
  SET search_path TO ''
  AS $function$
    select distinct
        delivery.recipient_email,
        delivery.notice_id,
        delivery.channel
    from pg_catalog.jsonb_to_recordset(p_candidates) as candidate(
        recipient_email text,
        notice_id text,
        channel text
    )
    join public.recommendation_deliveries as delivery
      on delivery.recipient_email = candidate.recipient_email
     and delivery.notice_id = candidate.notice_id
     and delivery.channel = candidate.channel;
$function$;

REVOKE ALL ON FUNCTION public.find_delivered_pairs(jsonb) FROM PUBLIC;

GRANT ALL ON FUNCTION public.find_delivered_pairs(jsonb) TO service_role;

-- query embedding과 공지 청크의 코사인 유사도를 계산해 가까운 청크를 반환한다.
CREATE FUNCTION public.match_notice_chunks (
  query_embedding extensions.vector,
  match_count     integer           DEFAULT 5
)
  RETURNS TABLE (
    id         bigint,
    notice_id  text,
    title      text,
    url        text,
    content    text,
    deadline   date,
    source_id  text,
    status     text,
    similarity double precision
  )
  LANGUAGE sql
  STABLE
  AS $function$
  select
    notice_chunks.id,
    notice_chunks.notice_id,
    notice_chunks.title,
    notice_chunks.url,
    notice_chunks.content,
    notice_chunks.deadline,
    notice_chunks.source_id,
    notice_chunks.status,
    1 - (notice_chunks.embedding <=> query_embedding) as similarity
  from notice_chunks
  where notice_chunks.embedding is not null
  order by notice_chunks.embedding <=> query_embedding
  limit match_count;
$function$;

GRANT ALL ON FUNCTION public.match_notice_chunks(extensions.vector, integer) TO anon;

GRANT ALL ON FUNCTION public.match_notice_chunks(extensions.vector, integer) TO authenticated;

GRANT ALL ON FUNCTION public.match_notice_chunks(extensions.vector, integer) TO service_role;

-- 크롤링한 공지를 청크 단위로 나누고 1,536차원 embedding과 함께 저장한다.
CREATE TABLE public.notice_chunks (
  id          bigint                   DEFAULT nextval('public.notice_chunks_id_seq'::regclass) NOT NULL,
  notice_id   text,
  title       text,
  url         text,
  content     text                     NOT NULL,
  deadline    date,
  source_id   text,
  status      text                     DEFAULT 'open'::text,
  embedding   extensions.vector(1536),
  created_at  timestamp with time zone DEFAULT now(),
  chunk_index integer                  NOT NULL
);

ALTER SEQUENCE public.notice_chunks_id_seq OWNED BY public.notice_chunks.id;

GRANT ALL ON SEQUENCE public.notice_chunks_id_seq TO anon;

GRANT ALL ON SEQUENCE public.notice_chunks_id_seq TO authenticated;

GRANT ALL ON SEQUENCE public.notice_chunks_id_seq TO service_role;

ALTER TABLE public.notice_chunks
  ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.notice_chunks
  ADD CONSTRAINT notice_chunks_notice_id_chunk_index_key UNIQUE (notice_id, chunk_index);

ALTER TABLE public.notice_chunks
  ADD CONSTRAINT notice_chunks_pkey PRIMARY KEY (id);

GRANT ALL ON public.notice_chunks TO anon;

GRANT ALL ON public.notice_chunks TO authenticated;

GRANT ALL ON public.notice_chunks TO service_role;

-- 사용자·공지·채널별 이메일 발송 성공 이력을 저장한다.
CREATE TABLE public.recommendation_deliveries (
  id              bigint                   GENERATED ALWAYS AS IDENTITY NOT NULL,
  recipient_email text                     NOT NULL,
  notice_id       text                     NOT NULL,
  channel         text                     DEFAULT 'email'::text NOT NULL,
  delivered_at    timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE public.recommendation_deliveries
  ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.recommendation_deliveries
  ADD CONSTRAINT recommendation_deliveries_channel_check CHECK (channel = 'email'::text);

ALTER TABLE public.recommendation_deliveries
  ADD CONSTRAINT recommendation_deliveries_pkey PRIMARY KEY (id);

ALTER TABLE public.recommendation_deliveries
  ADD CONSTRAINT recommendation_deliveries_recipient_email_notice_id_channel_key UNIQUE (recipient_email, notice_id, channel);

GRANT ALL ON public.recommendation_deliveries TO anon;

GRANT ALL ON public.recommendation_deliveries TO authenticated;

GRANT ALL ON public.recommendation_deliveries TO service_role;
