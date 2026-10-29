-- Ledger NZ — PostgreSQL schema (run in Supabase SQL editor)
-- Requires pgcrypto for gen_random_uuid()

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------
do $$ begin
  create type account_type as enum ('Income', 'Expense', 'Asset', 'Liability', 'Equity');
exception when duplicate_object then null; end $$;

do $$ begin
  create type transaction_source as enum ('CSV_Upload', 'AdHoc', 'ReceiptScan');
exception when duplicate_object then null; end $$;

do $$ begin
  create type transaction_status as enum ('Reconciled', 'Pending_Review', 'Ignored');
exception when duplicate_object then null; end $$;

do $$ begin
  create type depreciation_method as enum ('Straight_Line', 'Diminishing_Value', 'Maximum_Permissible');
exception when duplicate_object then null; end $$;

do $$ begin
  create type vehicle_purpose as enum ('Business', 'Personal');
exception when duplicate_object then null; end $$;

do $$ begin
  create type tax_period_type as enum ('GST', 'IncomeTax');
exception when duplicate_object then null; end $$;

-- ---------------------------------------------------------------------------
-- Tenancy
-- ---------------------------------------------------------------------------
create table if not exists public.organizations (
  id uuid primary key default gen_random_uuid(),
  name varchar(200) not null,
  gst_number varchar(20),
  created_at timestamptz not null default now()
);

create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  org_id uuid not null references public.organizations (id) on delete cascade,
  email varchar(320),
  full_name varchar(200),
  created_at timestamptz not null default now()
);

create index if not exists profiles_org_id_idx on public.profiles (org_id);

-- ---------------------------------------------------------------------------
-- Chart of accounts
-- ---------------------------------------------------------------------------
create table if not exists public.chart_of_accounts (
  account_id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations (id) on delete cascade,
  account_name varchar(200) not null,
  account_type account_type not null,
  tax_rate numeric(7, 2) not null default 15.00,
  business_claim_percentage numeric(7, 2) not null default 100.00,
  is_system boolean not null default false,
  created_at timestamptz not null default now(),
  unique (org_id, account_name),
  constraint chart_tax_rate_nonneg check (tax_rate >= 0 and tax_rate <= 100),
  constraint chart_claim_pct_range check (business_claim_percentage >= 0 and business_claim_percentage <= 100)
);

create index if not exists chart_of_accounts_org_type_idx
  on public.chart_of_accounts (org_id, account_type);

-- ---------------------------------------------------------------------------
-- Transactions
-- ---------------------------------------------------------------------------
create table if not exists public.transactions (
  transaction_id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations (id) on delete cascade,
  date date not null,
  account_id uuid references public.chart_of_accounts (account_id) on delete restrict,
  payee varchar(200) not null default '',
  description text not null default '',
  gross_amount numeric(14, 2) not null,
  gst_amount numeric(14, 2) not null default 0,
  net_amount numeric(14, 2) not null,
  business_claim_percentage numeric(7, 2) not null default 100.00,
  is_internal_transfer boolean not null default false,
  source transaction_source not null,
  status transaction_status not null default 'Pending_Review',
  import_hash varchar(64),
  external_id varchar(128),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (org_id, source, external_id),
  constraint transactions_claim_pct_range check (business_claim_percentage >= 0 and business_claim_percentage <= 100)
);

create index if not exists transactions_org_date_idx on public.transactions (org_id, date);
create index if not exists transactions_org_account_idx on public.transactions (org_id, account_id);
create index if not exists transactions_org_status_idx on public.transactions (org_id, status);
create unique index if not exists transactions_import_hash_idx
  on public.transactions (org_id, import_hash)
  where import_hash is not null;

-- ---------------------------------------------------------------------------
-- Receipts
-- ---------------------------------------------------------------------------
create table if not exists public.receipts (
  receipt_id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations (id) on delete cascade,
  transaction_id uuid references public.transactions (transaction_id) on delete set null,
  drive_file_id varchar(128),
  drive_file_url varchar(500),
  vendor_name varchar(200),
  extracted_amount numeric(14, 2),
  gst_number varchar(20),
  inferred_category varchar(200),
  confidence_score numeric(5, 4),
  ocr_raw text,
  created_at timestamptz not null default now()
);

create index if not exists receipts_org_tx_idx on public.receipts (org_id, transaction_id);

-- ---------------------------------------------------------------------------
-- Assets
-- ---------------------------------------------------------------------------
create table if not exists public.assets_depreciation (
  asset_id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations (id) on delete cascade,
  asset_name varchar(200) not null,
  asset_class varchar(40) not null default 'other',
  purchase_date date not null,
  original_cost numeric(14, 2) not null,
  depreciation_method depreciation_method not null,
  depreciation_rate numeric(7, 2) not null,
  business_use_percentage numeric(7, 2) not null default 100.00,
  accumulated_depreciation numeric(14, 2) not null default 0,
  created_at timestamptz not null default now(),
  constraint asset_cost_positive check (original_cost >= 0),
  constraint asset_rate_range check (depreciation_rate >= 0 and depreciation_rate <= 100),
  constraint asset_accum_range check (accumulated_depreciation >= 0)
);

-- ---------------------------------------------------------------------------
-- Vehicle logbook
-- ---------------------------------------------------------------------------
create table if not exists public.vehicle_logbook (
  log_id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations (id) on delete cascade,
  date date not null,
  odometer_start integer not null,
  odometer_end integer not null,
  distance integer generated always as (odometer_end - odometer_start) stored,
  purpose vehicle_purpose not null,
  notes text,
  created_at timestamptz not null default now(),
  constraint logbook_odo_order check (odometer_end >= odometer_start),
  constraint logbook_odo_nonneg check (odometer_start >= 0)
);

create index if not exists vehicle_logbook_org_date_idx on public.vehicle_logbook (org_id, date desc);

-- ---------------------------------------------------------------------------
-- Historical IRD records
-- ---------------------------------------------------------------------------
create table if not exists public.tax_records_historical (
  record_id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations (id) on delete cascade,
  period_type tax_period_type not null,
  start_date date not null,
  end_date date not null,
  total_income numeric(14, 2) not null default 0,
  tax_paid numeric(14, 2) not null default 0,
  notes text,
  created_at timestamptz not null default now(),
  constraint tax_period_order check (end_date >= start_date)
);

-- ---------------------------------------------------------------------------
-- Integrations & keyword rules
-- ---------------------------------------------------------------------------
create table if not exists public.categorization_rules (
  rule_id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations (id) on delete cascade,
  keyword varchar(120) not null,
  account_id uuid not null references public.chart_of_accounts (account_id) on delete cascade,
  priority integer not null default 100,
  unique (org_id, keyword)
);

-- ---------------------------------------------------------------------------
-- Provisioning: new auth user → org + profile + default COA + rules
-- ---------------------------------------------------------------------------
create or replace function public.provision_consultancy_defaults(p_org uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  uncat uuid;
  consulting uuid;
  motor uuid;
  bank_fees uuid;
  software uuid;
  phone uuid;
  advertising uuid;
  insurance uuid;
  ird_account uuid;
begin
  insert into public.chart_of_accounts (org_id, account_name, account_type, tax_rate, business_claim_percentage, is_system)
  values
    (p_org, 'Consulting Fees', 'Income', 15.00, 100.00, true),
    (p_org, 'Other Income', 'Income', 15.00, 100.00, false),
    (p_org, 'Uncategorised Expense', 'Expense', 15.00, 100.00, true),
    (p_org, 'Advertising', 'Expense', 15.00, 100.00, false),
    (p_org, 'Bank Fees', 'Expense', 0.00, 100.00, false),
    (p_org, 'Computer & Software', 'Expense', 15.00, 100.00, false),
    (p_org, 'Motor Vehicle', 'Expense', 15.00, 100.00, false),
    (p_org, 'Office Expenses', 'Expense', 15.00, 100.00, false),
    (p_org, 'Professional Development', 'Expense', 15.00, 100.00, false),
    (p_org, 'Subscriptions', 'Expense', 15.00, 100.00, false),
    (p_org, 'Telephone & Internet', 'Expense', 15.00, 100.00, false),
    (p_org, 'Travel', 'Expense', 15.00, 100.00, false),
    (p_org, 'Home Office', 'Expense', 15.00, 50.00, false),
    (p_org, 'Insurance', 'Expense', 15.00, 100.00, false),
    (p_org, 'Accounting Fees', 'Expense', 15.00, 100.00, false),
    (p_org, 'IRD / Tax Payments', 'Expense', 0.00, 100.00, true),
    (p_org, 'Business Bank Account', 'Asset', 0.00, 100.00, true),
    (p_org, 'Accounts Receivable', 'Asset', 15.00, 100.00, false),
    (p_org, 'Computer Equipment', 'Asset', 15.00, 100.00, false),
    (p_org, 'Motor Vehicles', 'Asset', 15.00, 100.00, true),
    (p_org, 'GST Payable', 'Liability', 0.00, 100.00, true),
    (p_org, 'Owner Equity', 'Equity', 0.00, 100.00, true),
    (p_org, 'Drawings', 'Equity', 0.00, 100.00, true),
    (p_org, 'Datacom income', 'Income', 15.00, 100.00, false),
    (p_org, 'NZ Post income', 'Income', 15.00, 100.00, false),
    (p_org, 'Unity income', 'Income', 15.00, 100.00, false),
    (p_org, 'Interest income', 'Income', 0.00, 100.00, false),
    (p_org, 'Mortgage interest', 'Expense', 0.00, 25.00, false),
    (p_org, 'Power and gas', 'Expense', 15.00, 25.00, false),
    (p_org, 'House and contents insurance', 'Expense', 15.00, 25.00, false),
    (p_org, 'Internet', 'Expense', 15.00, 50.00, false),
    (p_org, 'Business insurance', 'Expense', 15.00, 100.00, false),
    (p_org, 'Parking', 'Expense', 15.00, 100.00, false),
    (p_org, 'Client entertainment', 'Expense', 15.00, 100.00, false),
    (p_org, 'Low value assets', 'Expense', 15.00, 100.00, false),
    (p_org, 'Tea and snacks', 'Expense', 15.00, 100.00, false),
    (p_org, 'Business bank fees', 'Expense', 15.00, 100.00, false),
    (p_org, 'Business transport', 'Expense', 15.00, 100.00, false),
    (p_org, 'Air travel', 'Expense', 15.00, 100.00, false),
    (p_org, 'Petrol', 'Expense', 15.00, 100.00, false),
    (p_org, 'Business mobile', 'Expense', 15.00, 100.00, false),
    (p_org, 'Business car insurance', 'Expense', 15.00, 100.00, false),
    (p_org, 'Business accreditation', 'Expense', 15.00, 100.00, false),
    (p_org, 'Business car repairs', 'Expense', 15.00, 100.00, false),
    (p_org, 'Water', 'Expense', 15.00, 25.00, false),
    (p_org, 'Printing and stationery', 'Expense', 15.00, 100.00, false),
    (p_org, 'Wages - Pammy', 'Expense', 0.00, 100.00, false),
    (p_org, 'Wages - Mannu', 'Expense', 0.00, 100.00, false),
    (p_org, 'Gifts for clients', 'Expense', 15.00, 100.00, false),
    (p_org, 'Subcontracting', 'Expense', 0.00, 100.00, false),
    (p_org, 'ACC levy', 'Expense', 15.00, 100.00, false)
  on conflict (org_id, account_name) do nothing;

  select account_id into uncat from public.chart_of_accounts where org_id = p_org and account_name = 'Uncategorised Expense';
  select account_id into consulting from public.chart_of_accounts where org_id = p_org and account_name = 'Consulting Fees';
  select account_id into motor from public.chart_of_accounts where org_id = p_org and account_name = 'Motor Vehicle';
  select account_id into bank_fees from public.chart_of_accounts where org_id = p_org and account_name = 'Bank Fees';
  select account_id into software from public.chart_of_accounts where org_id = p_org and account_name = 'Computer & Software';
  select account_id into phone from public.chart_of_accounts where org_id = p_org and account_name = 'Telephone & Internet';
  select account_id into advertising from public.chart_of_accounts where org_id = p_org and account_name = 'Advertising';
  select account_id into insurance from public.chart_of_accounts where org_id = p_org and account_name = 'Insurance';
  select account_id into ird_account from public.chart_of_accounts where org_id = p_org and account_name = 'IRD / Tax Payments';

  insert into public.categorization_rules (org_id, keyword, account_id, priority)
  values
    (p_org, 'IRD', ird_account, 10),
    (p_org, 'INLAND REVENUE', ird_account, 10),
    (p_org, 'XERO', software, 20),
    (p_org, 'MICROSOFT', software, 30),
    (p_org, 'GOOGLE', software, 30),
    (p_org, 'ADOBE', software, 30),
    (p_org, 'SPARK', phone, 40),
    (p_org, 'ONE NZ', phone, 40),
    (p_org, 'VODAFONE', phone, 40),
    (p_org, 'BP ', motor, 50),
    (p_org, 'Z ENERGY', motor, 50),
    (p_org, 'MOBIL', motor, 50),
    (p_org, 'CALTEX', motor, 50),
    (p_org, 'BANK FEE', bank_fees, 15),
    (p_org, 'ACCOUNT FEE', bank_fees, 15),
    (p_org, 'FACEBOOK', advertising, 60),
    (p_org, 'META', advertising, 60),
    (p_org, 'LINKEDIN', advertising, 60),
    (p_org, 'TOWER', insurance, 70),
    (p_org, 'AA INSURANCE', insurance, 70),
    (p_org, 'CONSULT', consulting, 80),
    (p_org, 'INVOICE', consulting, 90)
  on conflict (org_id, keyword) do nothing;

  insert into public.categorization_rules (org_id, keyword, account_id, priority)
  select p_org, rule.keyword, account.account_id, rule.priority
  from (
    values
      ('DATACOMM', 'Datacom income', 25),
      ('DATACOM', 'Datacom income', 26),
      ('NZ POST', 'NZ Post income', 27)
  ) as rule(keyword, account_name, priority)
  join public.chart_of_accounts account
    on account.org_id = p_org and account.account_name = rule.account_name
  on conflict (org_id, keyword) do nothing;
end;
$$;

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  new_org uuid;
  display_name text;
begin
  display_name := coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1), 'Practice');

  insert into public.organizations (name)
  values (display_name || ' Consultancy')
  returning id into new_org;

  insert into public.profiles (id, org_id, email, full_name)
  values (new.id, new_org, new.email, display_name);

  perform public.provision_consultancy_defaults(new_org);
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- ---------------------------------------------------------------------------
-- Reporting
-- The sketch `GROUP BY account_type` while selecting account_name is not valid
-- PostgreSQL. These functions group by account so each line stays intact, and
-- they exclude internal transfers and ignored rows.
-- Expenses are stored as negative gross/net/GST. Input GST is sign-flipped
-- back to a positive claim. GST_to_Pay = output - input.
-- current_org_id() is created here because Postgres checks the function body
-- at creation time. rls.sql replaces it with the same definition.
-- ---------------------------------------------------------------------------
create or replace function public.current_org_id()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select org_id from public.profiles where id = auth.uid()
$$;

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
