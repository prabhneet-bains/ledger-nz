# Ledger NZ

Accounting system for a New Zealand consultancy. It replaces the spreadsheet with PostgreSQL, CSV bank imports, Google Drive receipts, and a local Qwen OCR pipeline reached over Tailscale.

| Layer | Stack | Free host |
| --- | --- | --- |
| Frontend | Next.js 14 (static export) | Cloudflare Pages |
| Backend | FastAPI + Python 3.12 | Render free web service |
| Database | Supabase PostgreSQL + RLS | Supabase |
| Login | Auth0, or Supabase Auth when Auth0 is unset | Auth0 free |
| Receipt files | Google Drive service account | Drive 15 GB |
| OCR | Ollama + Qwen 3.6 27B on a local GPU box | Tailscale + Wake-on-LAN |

Local development can run without Supabase. The API then uses SQLite and a development login. Production refuses to start unless Supabase and the JWT secret are set, and it refuses `ALLOW_DEV_AUTH`. When `AUTH0_DOMAIN` is set, production accepts only Auth0 access tokens.

## Money rules

Bank CSVs keep their sign. Positive amounts are income. Negative amounts are expenses. Manual entries and receipt scans are normalised to the account type (expenses stored negative).

Claimable GST on insert:

```
gst_amount = (gross_amount * (tax_rate / (100 + tax_rate))) * (business_claim_percentage / 100)
net_amount = gross_amount - gst_amount
```

GST to pay for a filing period, excluding internal transfers and ignored rows:

```
GST_to_Pay = SUM(output GST on Income) - SUM(input GST on Expense)
```

Expense GST is stored negative, so input GST is reported as a positive claim. P&L lines are `SUM(net_amount)` per account for the same filter. Grouping is by account name and type; grouping only by type would drop the account name.

A row is an internal transfer when the payee, details, or reference matches a transfer pattern (`TFR`, `TRANSFER`, a dashed NZ account number, and similar). Two matching rows with the same absolute amount on the same or next day are recorded as a contra pair. A normal purchase of the same amount is not treated as the other side of the transfer. Transfers are stored with `status = Ignored` and left out of P&L and GST.

NZ tax year used for Drive folders: **1 April – 31 March**, folder `FY2027` for a date in that year.

## Repository layout

```
backend/          FastAPI application
frontend/         Next.js UI
supabase/         SQL schema, RLS, upgrade, seeds
```

## 1. Supabase

1. Create a project.
2. In the SQL editor, run `supabase/schema.sql`, then `supabase/rls.sql`, then `supabase/seed.sql`. For Auth0 login, also run `supabase/migration_auth0.sql`.
3. If you previously applied an older Akahu draft of this schema, run `supabase/migration_csv.sql` as well.
4. Copy the project URL, anon key, service role key, and JWT secret into the API environment and the frontend environment.

Row Level Security isolates every financial table by the organisation on `profiles.id = auth.uid()`. The API sends the user JWT on normal requests, so those policies apply. A new auth user is provisioned with a consultancy chart of accounts and keyword rules.

Set `SUPABASE_URL` on the API. While that variable is empty, the API uses `DATABASE_URL` (SQLite by default) instead.

## 2. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy ..\.env.example .env
uvicorn app.main:app --reload --port 8000
```

For a local practice without Supabase, set `ALLOW_DEV_AUTH=true` and leave `SUPABASE_URL` empty. Do not enable that flag in production.

Tests:

```powershell
pytest
```

Deploy the `backend` folder with `backend/render.yaml`. Health check: `GET /health`. Koyeb and Cloud Run are the other free API hosts; see Free hosting below.

## 3. Frontend (Cloudflare Pages)

```powershell
cd frontend
copy .env.example .env.local
npm install
npm run dev
```

Set `NEXT_PUBLIC_DEV_AUTH=true` only for local UI work. Production Pages settings: framework **Next.js (static export)**, build command `npm run build`, output directory `out`. Set `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL`, and the `NEXT_PUBLIC_AUTH0_*` values when Auth0 is the login. Leave `NEXT_PUBLIC_DEV_AUTH` unset on Pages.

## 4. CSV import

The import screen asks the API to sniff headers, suggests a mapping (ANZ, ASB, BNZ, and Westpac-style exports), and lets you point Date, Amount or Debit/Credit, Payee, and Reference at your columns before anything is inserted. Re-importing the same file skips rows by a hash of date, amount, payee, reference, and occurrence.

Keyword rules (Spark, Z Energy, Adobe, and the rest of the seeded list) reconcile at 95% confidence. Anything unmatched, or under the 85% threshold, lands in Review with no account until you code it.

## 5. Receipts and local OCR

Share the Drive folder with the service account. Uploads land at:

```
/FY{TaxYear}/Expenses/{Category}/{Vendor}_{Date}.pdf
```

1. Install [Ollama](https://ollama.com) on the GPU workstation and pull the model named in `OCR_MODEL` (default `qwen3.6:27b`).
2. Bind Ollama so the API host can reach it over Tailscale (`OLLAMA_HOST=0.0.0.0:11434` plus an ACL).
3. Put the workstation MAC in `WOL_MAC_ADDRESS`. If `/api/tags` does not answer, the API sends a Wake-on-LAN magic packet, waits, and retries.
4. The model returns vendor, total, GST number, and a category. Below 85% confidence, or a category that does not match an account, the transaction is `Pending_Review`.

## 6. Auth0

Auth0 runs Universal Login for the static site (Authorization Code with PKCE). Access tokens stay in memory. The refresh token stays in a same-origin worker that `npm run dev` and `npm run build` copy into `public/`. The API checks the access token against Auth0's public keys, issuer, and audience. On first login it links that Auth0 user to a Supabase auth user and opens a practice. Later requests still go through row level security: the API mints a ten-minute Supabase user token on the server and does not send that token back to the browser.

The Auth0 free plan includes 25,000 monthly active users, brute-force protection, suspicious-IP throttling, passwordless login, and passkeys. Authenticator-app MFA is on the paid plans, so turn passkeys on for this ledger.

1. Create a free tenant. Add a Single Page Application. Add an API with identifier `https://ledger-nz-api`, signing algorithm RS256, and **Allow Offline Access** on.
2. In the SPA, set Allowed Callback URLs, Logout URLs, and Web Origins to `http://localhost:3000/` and `https://YOUR_PAGES_DOMAIN.pages.dev/`. Turn on refresh token rotation.
3. In the database connection, require a verified email before first login. Turn on Passkeys. Leave Brute Force Protection and Suspicious IP Throttling on.
4. Add a post-login Action so the access token carries the verified email. Auth0 drops non-namespaced custom claims from access tokens:

```javascript
exports.onExecutePostLogin = async (event, api) => {
  api.accessToken.setCustomClaim("https://ledger.nz/email", event.user.email);
  api.accessToken.setCustomClaim("https://ledger.nz/email_verified", event.user.email_verified);
  api.accessToken.setCustomClaim("https://ledger.nz/name", event.user.name);
};
```

5. Put `AUTH0_DOMAIN`, `AUTH0_AUDIENCE`, and `AUTH0_CLIENT_ID` on the API. Put the same domain, the SPA client id, and the audience in the Pages `NEXT_PUBLIC_AUTH0_*` variables. Do not create or store an Auth0 client secret for this SPA.
6. In Supabase, disable public email sign-ups so password registration is not a second door. The API still creates the shadow user with the service role. Run `supabase/migration_auth0.sql`. Keep the legacy JWT secret available; the API signs the short-lived user token with it.

Until those Auth0 variables are set, the email form continues to use Supabase Auth.

## Free hosting

Use this layout for a personal consultancy ledger at no charge:

1. **Cloudflare Pages** for the frontend. HTTPS is included, and the build publishes the security headers in `frontend/public/_headers`.
2. **Render** free web service for the API (`backend/render.yaml`). It sleeps after about 15 minutes idle and the next request takes about a minute. No card is required. Set `CORS_ORIGINS` to the Pages origin only, with no trailing slash: `https://ledger-nz.pages.dev`. The API also strips a trailing slash if one is saved.
3. **Supabase** free project for Postgres. Choose the Sydney region when it is offered. A free project pauses after about a week with no traffic. Do not use Render's free Postgres; that database expires.
4. **Auth0** free tenant for login, as above.
5. Leave OCR on the workstation and reach it only over Tailscale. Do not publish Ollama on a public port.

Koyeb's free instance and Google Cloud Run are the alternatives when a faster wake-up matters. Both ask for a card. On Cloud Run, set a billing alert so usage past the free allowance does not become a surprise charge. Fly.io no longer has a standing free allowance for new accounts.

Secrets stay in the host dashboards: Supabase service role, JWT secret, Auth0 settings, and the Google service-account JSON. The anon key and the Auth0 SPA client id are the only credentials that belong in the frontend.

## Security

Secrets stay in environment variables. Queries go through the Supabase client or SQLAlchemy bound parameters. CORS is an allow-list. Drive uses the service account only for the shared receipts folder. The development login is disabled when `APP_ENV=production`. With Auth0 configured, production also rejects Supabase session tokens, so a public Supabase sign-up cannot call the API. The Auth0 subject map is not readable by the anon or authenticated roles. The service role is used to create the first link, and ledger queries after that run as the signed-in user under the existing row level security policies.
