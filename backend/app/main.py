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
    return {"status": "ok", "env": current.app_env, "storage": "sqlite" if local_mode(current) else "supabase"}
