-- Link Auth0 subjects to Supabase auth users.
-- Run this once in the SQL editor after schema.sql and rls.sql.
-- The API uses the service role to write this table on first login, then
-- calls Postgres with a short-lived user JWT so the existing RLS policies apply.
-- Auth0 subjects are not UUIDs, so they cannot be stored in profiles.id.

create table if not exists public.auth_identities (
  provider text not null,
  subject text not null,
  user_id uuid not null references auth.users (id) on delete cascade,
  email varchar(320),
  created_at timestamptz not null default now(),
  primary key (provider, subject)
);

create index if not exists auth_identities_user_id_idx on public.auth_identities (user_id);

alter table public.auth_identities enable row level security;

revoke all on table public.auth_identities from anon, authenticated;
