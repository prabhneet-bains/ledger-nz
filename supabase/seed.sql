-- Optional demo historical tax rows. Run AFTER you have signed up once
-- so an organisation exists. Replace the org filter if you have several.

insert into public.tax_records_historical (
  org_id, period_type, start_date, end_date, total_income, tax_paid, notes
)
select
  p.org_id,
  'GST'::tax_period_type,
  d.start_date,
  d.end_date,
  d.total_income,
  d.tax_paid,
  'Seeded IRD comparison row'
from public.profiles p
cross join (
  values
    ('2025-04-01'::date, '2025-05-31'::date, 42000.00, 2100.00),
    ('2025-06-01'::date, '2025-07-31'::date, 38500.00, 1800.00),
    ('2025-08-01'::date, '2025-09-30'::date, 45120.00, 2400.00)
) as d(start_date, end_date, total_income, tax_paid)
where p.id = auth.uid()
on conflict do nothing;

insert into public.tax_records_historical (
  org_id, period_type, start_date, end_date, total_income, tax_paid, notes
)
select
  p.org_id,
  'IncomeTax'::tax_period_type,
  '2025-04-01'::date,
  '2026-03-31'::date,
  186400.00,
  31200.00,
  'Prior-year income tax (seed)'
from public.profiles p
where p.id = auth.uid()
on conflict do nothing;
