-- Fix: Auth0 first login needs service_role access to auth_identities.
-- Run once in the Supabase SQL editor if you already applied migration_auth0.sql
-- before the service_role grant was added.

revoke all on table public.auth_identities from anon, authenticated;
grant select, insert, update on table public.auth_identities to service_role;
