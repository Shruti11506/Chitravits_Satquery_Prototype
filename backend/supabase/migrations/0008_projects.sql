-- Projects: named workspaces that group conversations and hold knowledge
-- files + custom instructions. Run once in the Supabase SQL editor, after 0007.
--
-- Additive. Replaces the frontend's localStorage demo projects with real rows.
-- Ownership follows the app's existing identity model: every project belongs
-- to a profile (today the single workspace profile, resolved server-side by
-- profile_service.get_current_profile; later a real auth user).

create table if not exists projects (
    id uuid primary key default gen_random_uuid(),
    profile_id uuid not null references profiles(id) on delete cascade,
    name text not null check (char_length(btrim(name)) between 1 and 120),
    description text,
    icon text,
    color text,
    -- The project's custom instructions ("Custom Prompt" badge when non-empty).
    custom_instructions text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists projects_profile_updated_idx on projects (profile_id, updated_at desc);

-- A chat can belong to one project. Deleting a project keeps its chats (they
-- return to the normal history) -- it never deletes conversations.
alter table conversations
    add column if not exists project_id uuid references projects(id) on delete set null;

create index if not exists conversations_project_id_idx on conversations (project_id);

-- Knowledge files uploaded directly to a project (AOI vectors, PDFs, rasters).
-- Stored in the existing Satquery bucket at projects/{project_id}/{uuid}/{filename}.
create table if not exists project_files (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references projects(id) on delete cascade,
    name text not null,
    bucket text not null,
    storage_path text not null unique,
    mime_type text,
    file_size bigint,
    created_at timestamptz not null default now()
);

create index if not exists project_files_project_id_idx on project_files (project_id);

-- Same model as every other table (0004): RLS on, no anon/authenticated
-- policies -- only the backend's service_role reaches these rows.
alter table projects enable row level security;
alter table project_files enable row level security;
