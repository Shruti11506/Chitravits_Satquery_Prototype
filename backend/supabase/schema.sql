-- SatQuery AI backend foundation schema.
-- Run this once in the Supabase SQL editor (or via `supabase db push` if you
-- adopt the Supabase CLI later) against the project referenced in .env.
-- For a project that already ran an earlier version of this file (with a
-- `file_path` column instead of `storage_path`/`bucket`/etc.), run
-- migrations/0002_imagery_upload_fields.sql and 0003_conversations.sql
-- instead of this file.
--
-- No AI/model tables or columns are defined here -- see CLAUDE.md.

create extension if not exists "pgcrypto";

-- A chat thread. Its title never comes from an uploaded filename: it starts
-- as 'New Chat' and is set once from the first meaningful query ('auto') or
-- by a manual rename ('user').
create table if not exists conversations (
    id uuid primary key default gen_random_uuid(),
    title text not null default 'New Chat',
    title_source text not null default 'default'
        check (title_source in ('default', 'auto', 'user')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists imagery (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid references conversations(id),
    name text not null,
    source text,
    sensor text,
    acquisition_date timestamptz,
    original_filename text,
    bucket text,
    storage_path text,
    mime_type text,
    file_size bigint,
    storage_url text,
    cloud_cover float,
    latitude float,
    longitude float,
    bbox jsonb,
    metadata jsonb,
    -- Image pairs (migration 0006): shared id + 1 = reference, 2 = comparison.
    pair_id uuid,
    pair_position smallint,
    -- TIFF previews (migration 0007): separate PNG object; storage_path stays the original.
    preview_path text,
    preview_status text,
    created_at timestamptz not null default now(),
    constraint imagery_pair_position_check check (
        (pair_id is null and pair_position is null)
        or (pair_id is not null and pair_position in (1, 2))
    ),
    constraint imagery_preview_status_check
        check (preview_status is null or preview_status in ('ready', 'failed'))
);

create unique index if not exists imagery_pair_position_uidx
    on imagery (pair_id, pair_position) where pair_id is not null;

create table if not exists analysis_jobs (
    id uuid primary key default gen_random_uuid(),
    imagery_id uuid references imagery(id),
    -- Image 2 of an image-pair query (imagery_id is Image 1); NULL otherwise.
    comparison_imagery_id uuid references imagery(id),
    conversation_id uuid references conversations(id),
    analysis_type text not null,
    query text,
    status text not null default 'queued',
    model_name text,
    result_id uuid,
    error_message text,
    created_at timestamptz not null default now(),
    started_at timestamptz,
    completed_at timestamptz
);

create table if not exists analysis_results (
    id uuid primary key default gen_random_uuid(),
    job_id uuid references analysis_jobs(id),
    answer text,
    confidence float,
    model_name text,
    analysis_type text not null,
    raw_output jsonb,
    created_at timestamptz not null default now()
);

-- Deferred FK: analysis_jobs.result_id points at a row created after the job,
-- so it can only be added once analysis_results exists.
alter table analysis_jobs
    add constraint analysis_jobs_result_id_fkey
    foreign key (result_id) references analysis_results(id)
    on delete set null;

create table if not exists evidence (
    id uuid primary key default gen_random_uuid(),
    result_id uuid references analysis_results(id),
    evidence_type text not null,
    description text,
    source_reference text,
    bbox jsonb,
    confidence float,
    metadata jsonb,
    created_at timestamptz not null default now()
);

create table if not exists audit_logs (
    id uuid primary key default gen_random_uuid(),
    job_id uuid,
    event_type text not null,
    component text not null,
    message text,
    metadata jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_analysis_jobs_imagery_id on analysis_jobs(imagery_id);
create index if not exists idx_analysis_results_job_id on analysis_results(job_id);
create index if not exists idx_evidence_result_id on evidence(result_id);
create index if not exists idx_audit_logs_job_id on audit_logs(job_id);

-- Profile page (profiles table, profile_dashboard() aggregation, RLS): run
-- migrations/0004_profile_analytics.sql after this file -- it is additive and
-- re-runnable, so it is not duplicated here. The same goes for
-- 0005_user_settings.sql and 0008_projects.sql (projects, project_files,
-- conversations.project_id), which both reference `profiles`.

-- Storage bucket used by the backend (see app/services/storage_service.py).
-- Uncomment and run if you manage storage via SQL instead of the Supabase
-- dashboard's Storage UI:
--
-- insert into storage.buckets (id, name, public)
-- values ('satquery-data', 'satquery-data', false)
-- on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
-- The backend connects using the service_role key (SUPABASE_SECRET_KEY),
-- which always bypasses RLS -- so RLS is not required for the FastAPI ↔
-- Supabase path to work. Enable it anyway as defense-in-depth, in case the
-- anon/publishable key is ever used against these tables directly (it
-- currently isn't -- the frontend only talks to FastAPI, never to Supabase).
-- With RLS enabled and no policy defined for a role, that role gets zero
-- access by default, which is what we want here since there is no
-- direct-from-browser access pattern to support.
--
-- alter table imagery enable row level security;
-- alter table analysis_jobs enable row level security;
-- alter table analysis_results enable row level security;
-- alter table evidence enable row level security;
-- alter table audit_logs enable row level security;
--
-- No policies are created for anon/authenticated roles: service_role
-- traffic (the backend) bypasses RLS regardless, and no other role should
-- be able to read or write these tables.
