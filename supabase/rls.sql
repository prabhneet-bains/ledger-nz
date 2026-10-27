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
