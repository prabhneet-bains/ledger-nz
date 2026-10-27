"""SQLite ledger used when Supabase is not configured (local development and tests)."""

from __future__ import annotations

import os
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Account, AuthIdentity, Base, CategorizationRule, Organization, Profile, TaxRecord, Transaction

DEV_USER_ID = "00000000-0000-4000-8000-000000000001"
DEV_ORG_ID = "00000000-0000-4000-8000-000000000002"

# Keep names aligned with provision_consultancy_defaults in supabase/schema.sql.
DEFAULT_ACCOUNTS: list[tuple[str, str, str, str, bool]] = [
    ("Consulting Fees", "Income", "15.00", "100.00", True),
    ("Other Income", "Income", "15.00", "100.00", False),
    ("Uncategorised Expense", "Expense", "15.00", "100.00", True),
    ("Advertising", "Expense", "15.00", "100.00", False),
    ("Bank Fees", "Expense", "0.00", "100.00", False),
    ("Computer & Software", "Expense", "15.00", "100.00", False),
    ("Motor Vehicle", "Expense", "15.00", "100.00", False),
    ("Office Expenses", "Expense", "15.00", "100.00", False),
    ("Professional Development", "Expense", "15.00", "100.00", False),
    ("Subscriptions", "Expense", "15.00", "100.00", False),
    ("Telephone & Internet", "Expense", "15.00", "100.00", False),
    ("Travel", "Expense", "15.00", "100.00", False),
    ("Home Office", "Expense", "15.00", "50.00", False),
    ("Insurance", "Expense", "15.00", "100.00", False),
    ("Accounting Fees", "Expense", "15.00", "100.00", False),
    ("IRD / Tax Payments", "Expense", "0.00", "100.00", True),
    ("Business Bank Account", "Asset", "0.00", "100.00", True),
    ("Accounts Receivable", "Asset", "15.00", "100.00", False),
    ("Computer Equipment", "Asset", "15.00", "100.00", False),
    ("Motor Vehicles", "Asset", "15.00", "100.00", True),
    ("GST Payable", "Liability", "0.00", "100.00", True),
    ("Owner Equity", "Equity", "0.00", "100.00", True),
    ("Drawings", "Equity", "0.00", "100.00", True),
    # FY2027 statement lines for Bains consultancy services limited.
    ("Datacom income", "Income", "15.00", "100.00", False),
    ("NZ Post income", "Income", "15.00", "100.00", False),
    ("Unity income", "Income", "15.00", "100.00", False),
    ("Interest income", "Income", "0.00", "100.00", False),
    ("Mortgage interest", "Expense", "0.00", "25.00", False),
    ("Power and gas", "Expense", "15.00", "25.00", False),
    ("House and contents insurance", "Expense", "15.00", "25.00", False),
    ("Internet", "Expense", "15.00", "50.00", False),
    ("Business insurance", "Expense", "15.00", "100.00", False),
    ("Parking", "Expense", "15.00", "100.00", False),
    ("Client entertainment", "Expense", "15.00", "100.00", False),
    ("Low value assets", "Expense", "15.00", "100.00", False),
    ("Tea and snacks", "Expense", "15.00", "100.00", False),
    ("Business bank fees", "Expense", "15.00", "100.00", False),
    ("Business transport", "Expense", "15.00", "100.00", False),
    ("Air travel", "Expense", "15.00", "100.00", False),
    ("Petrol", "Expense", "15.00", "100.00", False),
    ("Business mobile", "Expense", "15.00", "100.00", False),
    ("Business car insurance", "Expense", "15.00", "100.00", False),
    ("Business accreditation", "Expense", "15.00", "100.00", False),
    ("Business car repairs", "Expense", "15.00", "100.00", False),
    ("Water", "Expense", "15.00", "25.00", False),
    ("Printing and stationery", "Expense", "15.00", "100.00", False),
    ("Wages - Pammy", "Expense", "0.00", "100.00", False),
    ("Wages - Mannu", "Expense", "0.00", "100.00", False),
    ("Gifts for clients", "Expense", "15.00", "100.00", False),
    ("Subcontracting", "Expense", "0.00", "100.00", False),
    ("ACC levy", "Expense", "15.00", "100.00", False),
]

DEFAULT_RULES: list[tuple[str, str, int]] = [
    ("IRD", "IRD / Tax Payments", 10),
    ("INLAND REVENUE", "IRD / Tax Payments", 10),
    ("XERO", "Computer & Software", 20),
    ("MICROSOFT", "Computer & Software", 30),
    ("GOOGLE", "Computer & Software", 30),
    ("ADOBE", "Computer & Software", 30),
    ("SPARK", "Telephone & Internet", 40),
    ("ONE NZ", "Telephone & Internet", 40),
    ("VODAFONE", "Telephone & Internet", 40),
    ("BP ", "Motor Vehicle", 50),
    ("Z ENERGY", "Motor Vehicle", 50),
    ("MOBIL", "Motor Vehicle", 50),
    ("CALTEX", "Motor Vehicle", 50),
    ("BANK FEE", "Bank Fees", 15),
    ("ACCOUNT FEE", "Bank Fees", 15),
    ("FACEBOOK", "Advertising", 60),
    ("META", "Advertising", 60),
    ("LINKEDIN", "Advertising", 60),
    ("TOWER", "Insurance", 70),
    ("AA INSURANCE", "Insurance", 70),
    ("CONSULT", "Consulting Fees", 80),
    ("INVOICE", "Consulting Fees", 90),
    ("DATACOMM", "Datacom income", 25),
    ("DATACOM", "Datacom income", 26),
    ("NZ POST", "NZ Post income", 27),
]

_engine = None
_engine_url: str | None = None
_Session: sessionmaker | None = None


def _sqlite_url(url: str) -> bool:
    return url.startswith("sqlite")


def reset_engine() -> None:
    global _engine, _engine_url, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _engine_url = None
    _Session = None


def get_engine():
    global _engine, _engine_url, _Session
    url = get_settings().database_url
    if _engine is not None and _engine_url != url:
        reset_engine()
    if _engine is None:
        connect_args = {"check_same_thread": False} if _sqlite_url(url) else {}
        _engine = create_engine(url, connect_args=connect_args, future=True)
        if _sqlite_url(url):

            @event.listens_for(_engine, "connect")
            def _fk(dbapi_connection, _):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        _Session = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)
        _engine_url = url
    return _engine


def SessionLocal() -> Session:
    get_engine()
    assert _Session is not None
    return _Session()


def init_local_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    if not _sqlite_url(str(engine.url)):
        return
    with engine.begin() as conn:
        names = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(receipts)").fetchall()}
        if names and "ocr_raw" not in names:
            conn.exec_driver_sql("ALTER TABLE receipts ADD COLUMN ocr_raw TEXT")
        txn_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(transactions)").fetchall()}
        if txn_cols and "business_claim_percentage" not in txn_cols:
            conn.exec_driver_sql(
                "ALTER TABLE transactions ADD COLUMN business_claim_percentage TEXT NOT NULL DEFAULT '100.00'"
            )
        asset_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(assets_depreciation)").fetchall()}
        if asset_cols and "asset_class" not in asset_cols:
            conn.exec_driver_sql("ALTER TABLE assets_depreciation ADD COLUMN asset_class TEXT NOT NULL DEFAULT 'other'")
        if asset_cols and "business_use_percentage" not in asset_cols:
            conn.exec_driver_sql(
                "ALTER TABLE assets_depreciation ADD COLUMN business_use_percentage TEXT NOT NULL DEFAULT '100.00'"
            )


def account_id_for(org_id: str, name: str) -> str:
    return str(uuid.uuid5(uuid.UUID(org_id), name))


def add_default_chart(session: Session, org_id: str) -> None:
    ids: dict[str, str] = {}
    for name, account_type, rate, claim, system in DEFAULT_ACCOUNTS:
        account_id = account_id_for(org_id, name)
        ids[name] = account_id
        if session.get(Account, account_id) is not None:
            continue
        session.add(
            Account(
                account_id=account_id,
                org_id=org_id,
                account_name=name,
                account_type=account_type,
                tax_rate=rate,
                business_claim_percentage=claim,
                is_system=system,
            )
        )
    session.flush()
    for keyword, account_name, priority in DEFAULT_RULES:
        existing = session.scalar(
            select(CategorizationRule.rule_id).where(
                CategorizationRule.org_id == org_id,
                CategorizationRule.keyword == keyword,
            )
        )
        if existing:
            continue
        session.add(
            CategorizationRule(
                org_id=org_id,
                keyword=keyword,
                account_id=ids[account_name],
                priority=priority,
            )
        )


def ensure_default_accounts() -> None:
    """Add chart accounts introduced after the local practice was first seeded."""
    session = SessionLocal()
    try:
        if session.get(Organization, DEV_ORG_ID) is None:
            return
        add_default_chart(session, DEV_ORG_ID)
        session.commit()
    finally:
        session.close()


def ensure_local_auth0_user(session: Session, subject: str, email: str, full_name: str) -> str:
    """Create a practice for an Auth0 subject, or return the one already linked."""
    identity = session.get(AuthIdentity, ("auth0", subject))
    if identity:
        return identity.user_id
    normalised = email.strip().lower()
    display = full_name.strip() or normalised.split("@", 1)[0] or "Practice"
    existing = session.scalar(select(Profile).where(Profile.email == normalised))
    if existing:
        session.add(AuthIdentity(provider="auth0", subject=subject, user_id=existing.id, email=normalised))
        session.commit()
        return existing.id
    user_id = str(uuid.uuid4())
    org_id = str(uuid.uuid4())
    session.add(Organization(id=org_id, name=f"{display} Consultancy"))
    session.flush()
    session.add(Profile(id=user_id, org_id=org_id, email=normalised, full_name=display))
    session.add(AuthIdentity(provider="auth0", subject=subject, user_id=user_id, email=normalised))
    add_default_chart(session, org_id)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raced = session.get(AuthIdentity, ("auth0", subject))
        if raced:
            return raced.user_id
        raise
    return user_id


def seed_local_practice() -> None:
    session = SessionLocal()
    try:
        if session.get(Profile, DEV_USER_ID):
            return
        session.add(Organization(id=DEV_ORG_ID, name="Local Consultancy", gst_number=None))
        session.flush()
        session.add(
            Profile(id=DEV_USER_ID, org_id=DEV_ORG_ID, email="dev@ledger.local", full_name="Local Practice")
        )
        session.flush()
        add_default_chart(session, DEV_ORG_ID)
        session.add_all(
            [
                TaxRecord(
                    org_id=DEV_ORG_ID,
                    period_type="GST",
                    start_date=date(2026, 4, 1),
                    end_date=date(2026, 5, 31),
                    total_income="42000.00",
                    tax_paid="2100.00",
                    notes="Prior GST return",
                ),
                TaxRecord(
                    org_id=DEV_ORG_ID,
                    period_type="GST",
                    start_date=date(2026, 6, 1),
                    end_date=date(2026, 7, 31),
                    total_income="38500.00",
                    tax_paid="1800.00",
                    notes="Prior GST return",
                ),
                TaxRecord(
                    org_id=DEV_ORG_ID,
                    period_type="IncomeTax",
                    start_date=date(2025, 4, 1),
                    end_date=date(2026, 3, 31),
                    total_income="186400.00",
                    tax_paid="31200.00",
                    notes="Prior-year income tax",
                ),
            ]
        )
        session.commit()
    finally:
        session.close()


def statement_seed_enabled() -> bool:
    return os.getenv("SEED_FY_STATEMENT", "true").lower() != "false"


# April–September 2026 (FY2027) from the practice workbook. April–June are blank.
# Income figures are GST-inclusive. Expense figures are the GST-exclusive business share
# already apportioned (home office at 25% or 50%), so the posted line is claimed at 100%.
_STATEMENT_MONTHS = {
    "2026-07": date(2026, 7, 31),
    "2026-08": date(2026, 8, 31),
    "2026-09": date(2026, 9, 30),
}
_STATEMENT_INCOME: list[tuple[str, str, str]] = [
    ("2026-08", "Datacom income", "32516.25"),
    ("2026-09", "Datacom income", "22425.00"),
]
_STATEMENT_EXPENSES: list[tuple[str, str, str]] = [
    ("2026-07", "Mortgage interest", "524.00"),
    ("2026-08", "Mortgage interest", "524.00"),
    ("2026-09", "Mortgage interest", "524.00"),
    ("2026-07", "Power and gas", "62.40"),
    ("2026-08", "Power and gas", "59.60"),
    ("2026-09", "Power and gas", "65.00"),
    ("2026-07", "House and contents insurance", "35.09"),
    ("2026-08", "House and contents insurance", "35.09"),
    ("2026-09", "House and contents insurance", "35.09"),
    ("2026-07", "Internet", "30.00"),
    ("2026-08", "Internet", "30.00"),
    ("2026-09", "Internet", "30.00"),
    ("2026-09", "Subscriptions", "219.00"),
    ("2026-07", "Tea and snacks", "306.00"),
    ("2026-08", "Tea and snacks", "125.00"),
    ("2026-08", "Air travel", "1420.00"),
    ("2026-07", "Business mobile", "38.00"),
    ("2026-08", "Business mobile", "38.00"),
    ("2026-09", "Business mobile", "38.00"),
    ("2026-07", "Water", "31.00"),
    ("2026-08", "Water", "18.87"),
    ("2026-09", "Water", "29.20"),
    ("2026-08", "Printing and stationery", "218.64"),
    ("2026-07", "Wages - Pammy", "6000.00"),
    ("2026-08", "Wages - Pammy", "6000.00"),
    ("2026-09", "Wages - Pammy", "6000.00"),
    ("2026-07", "Wages - Mannu", "3000.00"),
    ("2026-08", "Wages - Mannu", "3000.00"),
    ("2026-09", "Wages - Mannu", "3000.00"),
]
# Recent columns on the depreciation sheet are 20% of original cost each year.
# Purchase dates are not on the sheet. Office equipment is already written off.
_STATEMENT_ASSETS: list[tuple[str, str, str, str]] = [
    ("Plant and equipment", "2173.90", "20.00", "2022-04-01"),
    ("Motor vehicle", "14000.00", "20.00", "2022-04-01"),
    ("Motor vehicle (second)", "12013.04", "20.00", "2022-04-01"),
    ("Office equipment", "2782.61", "20.00", "2017-04-01"),
]


def _inclusive_gross(account: dict, exclusive: Decimal) -> Decimal:
    from app.services.gst import money as round_money

    rate = Decimal(str(account["tax_rate"]))
    if rate <= 0:
        return round_money(exclusive)
    return round_money(exclusive * (Decimal("100") + rate) / Decimal("100"))


def ensure_fy2027_statement() -> None:
    """Add the FY2027 workbook accounts, July–September totals, and asset register."""
    from app.store import SqlStore

    session = SessionLocal()
    try:
        if session.get(Organization, DEV_ORG_ID) is None:
            return
        add_default_chart(session, DEV_ORG_ID)
        org = session.get(Organization, DEV_ORG_ID)
        if org and org.name == "Local Consultancy":
            org.name = "Bains consultancy services limited"
        if org and not org.gst_number:
            org.gst_number = "134-099-909"
        session.commit()
        store = SqlStore(session)
        accounts = {row["account_name"]: row for row in store.list_accounts(DEV_ORG_ID)}
        for month_key, account_name, amount in _STATEMENT_INCOME:
            _post_statement_line(store, accounts, month_key, account_name, Decimal(amount), income=True)
        for month_key, account_name, amount in _STATEMENT_EXPENSES:
            _post_statement_line(store, accounts, month_key, account_name, Decimal(amount), income=False)
        _align_bank_to_statement(store, accounts)
        known = {row["asset_name"] for row in store.list_assets(DEV_ORG_ID)}
        for name, cost, rate, purchased in _STATEMENT_ASSETS:
            if name in known:
                continue
            store.insert_asset(
                {
                    "org_id": DEV_ORG_ID,
                    "asset_name": name,
                    "asset_class": "other",
                    "purchase_date": purchased,
                    "original_cost": cost,
                    "depreciation_method": "Straight_Line",
                    "depreciation_rate": rate,
                    "business_use_percentage": "100",
                    "accumulated_depreciation": "0",
                }
            )
    finally:
        session.close()


def _month_bounds(month_key: str) -> tuple[date, date]:
    year, month = (int(part) for part in month_key.split("-"))
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def _month_bank_rows(session: Session, month_key: str) -> list[Transaction]:
    start, end = _month_bounds(month_key)
    rows = session.scalars(
        select(Transaction).where(
            Transaction.org_id == DEV_ORG_ID,
            Transaction.date >= start,
            Transaction.date < end,
        )
    ).all()
    return [row for row in rows if not (row.import_hash or "").startswith("fy2027:")]


def _shareholder_wage(row: Transaction) -> bool:
    text = f"{row.payee or ''} {row.description or ''}".upper()
    return "PRABHNEET" in text and "SHAREHOLDER" in text and abs(Decimal(str(row.gross_amount))) == Decimal("1500.00")


def _bank_already_has(session: Session, month_key: str, account_name: str) -> bool:
    """Skip a workbook total when the bank feed already contains that amount."""
    rows = _month_bank_rows(session, month_key)
    if account_name == "Datacom income":
        return any("DATACOM" in (row.payee or "").upper() for row in rows)
    if account_name == "Printing and stationery":
        return any("PRINT" in (row.payee or "").upper() for row in rows)
    if account_name == "Subscriptions":
        return any("GOOGLE" in (row.payee or "").upper() for row in rows)
    if account_name == "Wages - Pammy":
        paid = sum((abs(Decimal(str(row.gross_amount))) for row in rows if _shareholder_wage(row)), Decimal("0"))
        return paid >= Decimal("6000.00")
    return False


def _drop_statement_line(session: Session, account_name: str, month_key: str) -> None:
    row = session.scalar(
        select(Transaction).where(
            Transaction.org_id == DEV_ORG_ID,
            Transaction.import_hash == f"fy2027:{account_name}:{month_key}",
        )
    )
    if row is None:
        return
    session.delete(row)
    session.commit()


def _align_bank_to_statement(store, accounts: dict) -> None:
    """Point bank lines that are already on the workbook at the matching account."""
    from app.services.ledger import recalc_transaction

    printing = accounts["Printing and stationery"]["account_id"]
    subscriptions = accounts["Subscriptions"]["account_id"]
    wages = accounts["Wages - Pammy"]["account_id"]
    interest = accounts["Interest income"]["account_id"]
    rows = store.session.scalars(select(Transaction).where(Transaction.org_id == DEV_ORG_ID)).all()
    for row in rows:
        if (row.import_hash or "").startswith("fy2027:"):
            continue
        payee = (row.payee or "").upper()
        target = None
        if "PRINTZONE" in payee:
            target = printing
        elif "GOOGLE" in payee and "PHYSIO" in payee:
            target = subscriptions
        elif "INTEREST" in payee:
            target = interest
        elif _shareholder_wage(row):
            target = wages
        if target is None or row.account_id == target:
            continue
        recalc_transaction(store, DEV_ORG_ID, row.transaction_id, target, Decimal(str(row.gross_amount)), Decimal("100"))
        store.update_transaction(DEV_ORG_ID, row.transaction_id, {"status": "Reconciled"})


def _post_statement_line(store, accounts: dict, month_key: str, account_name: str, amount: Decimal, income: bool) -> None:
    from app.services.ledger import insert_transaction
    from app.store import DuplicateTransaction

    account = accounts.get(account_name)
    if account is None:
        return
    if _bank_already_has(store.session, month_key, account_name):
        _drop_statement_line(store.session, account_name, month_key)
        return
    gross = amount if income else _inclusive_gross(account, amount)
    label = _STATEMENT_MONTHS[month_key].strftime("%B %Y")
    note = "FY2027 statement"
    if not income and Decimal(str(account["business_claim_percentage"])) < 100:
        note = "FY2027 statement, home-office share already apportioned"
    try:
        insert_transaction(
            store,
            org_id=DEV_ORG_ID,
            txn_date=_STATEMENT_MONTHS[month_key],
            account_id=account["account_id"],
            description=f"{label} {account_name}. {note}.",
            payee=account_name,
            gross_amount=gross,
            source="AdHoc",
            status="Reconciled",
            import_hash=f"fy2027:{account_name}:{month_key}",
            business_claim_percentage=Decimal("100"),
        )
    except DuplicateTransaction:
        return
