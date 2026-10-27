-- Upgrade an earlier Akahu draft to the CSV ledger.
-- Safe to run once after supabase/schema.sql from that draft.
-- Fresh installs that already ran the current schema.sql can skip this file.

alter type transaction_source add value if not exists 'CSV_Upload';
alter type transaction_status add value if not exists 'Ignored';

alter table public.transactions add column if not exists payee varchar(200) not null default '';
alter table public.transactions add column if not exists is_internal_transfer boolean not null default false;
alter table public.transactions add column if not exists import_hash varchar(64);

create unique index if not exists transactions_import_hash_idx
  on public.transactions (org_id, import_hash)
  where import_hash is not null;

-- Reporting functions also live in schema.sql. Repeated here so upgrades get them
-- without recreating tables.
create or replace function public.pnl_by_account(p_start date, p_end date)
returns table (account_name varchar, account_type account_type, net_amount numeric)
language sql
stable
security invoker
set search_path = public
as $$
  select a.account_name,
         a.account_type,
         sum(t.net_amount) as net_amount
  from public.transactions t
  join public.chart_of_accounts a on a.account_id = t.account_id
  where t.org_id = public.current_org_id()
    and t.date between p_start and p_end
    and t.is_internal_transfer = false
    and t.status <> 'Ignored'
  group by a.account_name, a.account_type
$$;

create or replace function public.gst_period(p_start date, p_end date)
returns table (output_gst numeric, input_gst numeric, gst_to_pay numeric)
language sql
stable
security invoker
set search_path = public
as $$
  select
    coalesce(sum(t.gst_amount) filter (where a.account_type = 'Income'), 0) as output_gst,
    coalesce(sum(-t.gst_amount) filter (where a.account_type = 'Expense'), 0) as input_gst,
    coalesce(sum(t.gst_amount) filter (where a.account_type = 'Income'), 0)
      - coalesce(sum(-t.gst_amount) filter (where a.account_type = 'Expense'), 0) as gst_to_pay
  from public.transactions t
  join public.chart_of_accounts a on a.account_id = t.account_id
  where t.org_id = public.current_org_id()
    and t.date between p_start and p_end
    and t.is_internal_transfer = false
    and t.status <> 'Ignored'
$$;
