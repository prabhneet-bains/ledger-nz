-- Ledger NZ — Row Level Security
-- Every policy scopes rows to the caller's organisation.

alter table public.organizations enable row level security;
alter table public.profiles enable row level security;
alter table public.chart_of_accounts enable row level security;
alter table public.transactions enable row level security;
alter table public.receipts enable row level security;
alter table public.assets_depreciation enable row level security;
alter table public.vehicle_logbook enable row level security;
alter table public.tax_records_historical enable row level security;
alter table public.categorization_rules enable row level security;

create or replace function public.current_org_id()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select org_id from public.profiles where id = auth.uid()
$$;

-- Profiles: users see only their own row
drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles
  for select using (id = auth.uid());

drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own on public.profiles
  for update using (id = auth.uid()) with check (id = auth.uid());

-- Organisations: members can read/update their org
drop policy if exists orgs_select_member on public.organizations;
create policy orgs_select_member on public.organizations
  for select using (id = public.current_org_id());

drop policy if exists orgs_update_member on public.organizations;
create policy orgs_update_member on public.organizations
  for update using (id = public.current_org_id()) with check (id = public.current_org_id());

-- Generic org isolation for remaining tables
drop policy if exists coa_all on public.chart_of_accounts;
create policy coa_all on public.chart_of_accounts
  for all using (org_id = public.current_org_id())
  with check (org_id = public.current_org_id());

drop policy if exists tx_all on public.transactions;
create policy tx_all on public.transactions
  for all using (org_id = public.current_org_id())
  with check (org_id = public.current_org_id());

drop policy if exists receipts_all on public.receipts;
create policy receipts_all on public.receipts
  for all using (org_id = public.current_org_id())
  with check (org_id = public.current_org_id());

drop policy if exists assets_all on public.assets_depreciation;
create policy assets_all on public.assets_depreciation
  for all using (org_id = public.current_org_id())
  with check (org_id = public.current_org_id());

drop policy if exists logbook_all on public.vehicle_logbook;
create policy logbook_all on public.vehicle_logbook
  for all using (org_id = public.current_org_id())
  with check (org_id = public.current_org_id());

drop policy if exists tax_hist_all on public.tax_records_historical;
create policy tax_hist_all on public.tax_records_historical
  for all using (org_id = public.current_org_id())
  with check (org_id = public.current_org_id());

drop policy if exists rules_all on public.categorization_rules;
create policy rules_all on public.categorization_rules
  for all using (org_id = public.current_org_id())
  with check (org_id = public.current_org_id());

-- Table privileges (RLS still limits which rows each role can see).
-- Fresh Supabase projects do not always inherit these for SQL-created tables.
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
