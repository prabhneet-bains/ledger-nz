from datetime import date
from decimal import Decimal
from uuid import UUID

from app.services.gst import gst_on_insert


def apply_sign(gross: Decimal, account_type: str, source: str) -> Decimal:
    """CSV keeps the bank sign. Manual and receipt amounts are normalised to the account type."""
    if source == "CSV_Upload":
        return gross
    if account_type == "Expense":
        return -abs(gross)
    if account_type == "Income":
        return abs(gross)
    return gross


def claim_for(account: dict, override: Decimal | None) -> Decimal:
    """Partial business use applies to expenses. Other account types stay at 100%."""
    if account.get("account_type") not in {"Expense", "Asset"}:
        return Decimal("100")
    raw = account["business_claim_percentage"] if override is None else override
    claim = Decimal(str(raw))
    if claim < 0 or claim > 100:
        raise ValueError("Business use must be between 0 and 100")
    return claim


def amounts_for_account(
    gross: Decimal,
    account: dict,
    source: str,
    claim: Decimal | None = None,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    signed = apply_sign(Decimal(str(gross)), account["account_type"], source)
    used = claim_for(account, claim)
    gst, net = gst_on_insert(signed, Decimal(str(account["tax_rate"])), used)
    return signed, gst, net, used


def insert_transaction(
    store,
    *,
    org_id: str,
    txn_date: date,
    account_id: UUID | str | None,
    description: str,
    gross_amount: Decimal,
    source: str,
    status: str,
    payee: str = "",
    is_internal_transfer: bool = False,
    import_hash: str | None = None,
    external_id: str | None = None,
    metadata: dict | None = None,
    business_claim_percentage: Decimal | None = None,
) -> dict:
    gross = Decimal(str(gross_amount))
    gst = Decimal("0")
    net = gross
    claim_used = Decimal("100")
    account_key = str(account_id) if account_id else None
    if is_internal_transfer:
        account_key = None
        status = "Ignored"
        gst = Decimal("0")
        net = gross
    elif account_key:
        account = store.get_account(org_id, account_key)
        if not account:
            raise ValueError("Unknown account_id")
        gross, gst, net, claim_used = amounts_for_account(gross, account, source, business_claim_percentage)

    payload = {
        "org_id": org_id,
        "date": txn_date.isoformat(),
        "account_id": account_key,
        "payee": (payee or "")[:200],
        "description": description,
        "gross_amount": gross,
        "gst_amount": gst,
        "net_amount": net,
        "business_claim_percentage": claim_used,
        "is_internal_transfer": is_internal_transfer,
        "source": source,
        "status": status,
        "import_hash": import_hash,
        "external_id": external_id,
        "metadata": metadata or {},
    }
    return store.insert_transaction(payload)


def recalc_transaction(
    store,
    org_id: str,
    transaction_id: str,
    account_id: UUID,
    gross: Decimal,
    claim: Decimal | None = None,
) -> dict:
    existing = store.get_transaction(org_id, transaction_id)
    if not existing:
        raise ValueError("Unknown transaction")
    account = store.get_account(org_id, str(account_id))
    if not account:
        raise ValueError("Unknown account_id")
    signed, gst, net, claim_used = amounts_for_account(Decimal(str(gross)), account, existing["source"], claim)
    return store.update_transaction(
        org_id,
        transaction_id,
        {
            "account_id": str(account_id),
            "gross_amount": signed,
            "gst_amount": gst,
            "net_amount": net,
            "business_claim_percentage": claim_used,
            "is_internal_transfer": False,
        },
    )
