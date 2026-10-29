-- Fix: PostgREST "permission denied for table profiles" (and other ledger tables).
-- RLS policies alone are not enough; the authenticated role also needs GRANTs.
-- Run once in the Supabase SQL editor.

grant usage on schema public to anon, authenticated, service_role;

grant select, update on table public.profiles to authenticated;
grant select, update on table public.organizations to authenticated;
grant select, insert, update, delete on table public.chart_of_accounts to authenticated;
grant select, insert, update, delete on table public.transactions to authenticated;
grant select, insert, update, delete on table public.receipts to authenticated;
grant select, insert, update, delete on table public.assets_depreciation to authenticated;
grant select, insert, update, delete on table public.vehicle_logbook to authenticated;
grant select, insert, update, delete on table public.tax_records_historical to authenticated;
grant select, insert, update, delete on table public.categorization_rules to authenticated;

grant select, insert, update, delete on table public.organizations to service_role;
grant select, insert, update, delete on table public.profiles to service_role;
grant select, insert, update, delete on table public.chart_of_accounts to service_role;
grant select, insert, update, delete on table public.transactions to service_role;
grant select, insert, update, delete on table public.receipts to service_role;
grant select, insert, update, delete on table public.assets_depreciation to service_role;
grant select, insert, update, delete on table public.vehicle_logbook to service_role;
grant select, insert, update, delete on table public.tax_records_historical to service_role;
grant select, insert, update, delete on table public.categorization_rules to service_role;
grant usage, select on all sequences in schema public to authenticated, service_role;
grant execute on function public.current_org_id() to authenticated, service_role;
grant execute on function public.pnl_by_account(date, date) to authenticated, service_role;
grant execute on function public.gst_period(date, date) to authenticated, service_role;

-- Keep Auth0 subject links off the browser roles when that table exists.
do $$
begin
  if to_regclass('public.auth_identities') is not null then
    execute 'revoke all on table public.auth_identities from anon, authenticated';
    execute 'grant select, insert, update on table public.auth_identities to service_role';
  end if;
end $$;
