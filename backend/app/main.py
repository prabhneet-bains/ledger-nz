import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import assert_production, get_settings
from app.deps import local_mode
from app.localdb import ensure_default_accounts, ensure_fy2027_statement, init_local_db, seed_local_practice, statement_seed_enabled
from app.routers import accounts, assets, auth, csv_import, dashboard, logbook, receipts, tax, transactions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

settings = get_settings()
assert_production(settings)

app = FastAPI(
    title="Ledger NZ API",
    version="1.1.0",
    description="GST-aware accounting API for New Zealand consultancies.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Auth0-Id-Token"],
)

app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(csv_import.router)
app.include_router(receipts.router)
app.include_router(logbook.router)
app.include_router(dashboard.router)
app.include_router(tax.router)
app.include_router(assets.router)


@app.on_event("startup")
def startup() -> None:
    current = get_settings()
    if local_mode(current):
        init_local_db()
        if current.allow_dev_auth and current.app_env != "production":
            seed_local_practice()
            ensure_default_accounts()
            if statement_seed_enabled():
                ensure_fy2027_statement()


@app.get("/health")
def health():
    current = get_settings()
    origins = current.cors_origin_list
    return {
        "status": "ok",
        "env": current.app_env,
        "storage": "sqlite" if local_mode(current) else "supabase",
        # Lets us confirm Render picked up the Pages origin without a trailing slash.
        "cors_allows_pages": "https://ledger-nz.pages.dev" in origins,
        "auth0": bool(current.auth0_host and current.auth0_audience.strip()),
        "auth0_host": current.auth0_host or None,
    }
