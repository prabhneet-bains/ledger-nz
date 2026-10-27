-- Add raw OCR JSON storage for receipts created before this column existed.
alter table public.receipts add column if not exists ocr_raw text;

-- Business-use percentage stored on each transaction. 100 keeps the full expense deductible.
alter table public.transactions
  add column if not exists business_claim_percentage numeric(7, 2) not null default 100.00;

alter table public.assets_depreciation
  add column if not exists asset_class varchar(40) not null default 'other';

alter table public.assets_depreciation
  add column if not exists business_use_percentage numeric(7, 2) not null default 100.00;
