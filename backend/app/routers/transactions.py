from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import Principal, get_principal
from app.schemas import BulkCode, TransactionCreate, TransactionOut, TransactionPatch
from app.services.csv_engine import normalize_party
from app.services.ledger import insert_transaction, recalc_transaction

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=list[TransactionOut])
def list_transactions(
    principal: Annotated[Principal, Depends(get_principal)],
    status: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(200, le=500),
):
    return principal.store.list_transactions(principal.org_id, status=status, start=start, end=end, limit=limit)


@router.get("/similar", response_model=list[TransactionOut])
def similar_transactions(
    principal: Annotated[Principal, Depends(get_principal)],
    payee: str,
    direction: Literal["in", "out"],
    exclude: UUID | None = None,
    start: date | None = None,
    end: date | None = None,
):
    return _similar(principal, payee, direction, str(exclude) if exclude else None, start, end)


@router.post("/bulk-code")
def bulk_code(body: BulkCode, principal: Annotated[Principal, Depends(get_principal)]):
    account = principal.store.get_account(principal.org_id, str(body.account_id))
    if not account:
        raise HTTPException(status_code=400, detail="Choose an account before reconciling")
    updated = 0
    payee = ""
    for transaction_id in body.transaction_ids:
        existing = principal.store.get_transaction(principal.org_id, str(transaction_id))
        if not existing or existing.get("is_internal_transfer") or existing.get("status") == "Ignored":
            continue
        try:
            recalc_transaction(
                principal.store,
                principal.org_id,
                str(transaction_id),
                body.account_id,
                Decimal(str(existing["gross_amount"])),
                body.business_claim_percentage,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        principal.store.update_transaction(
            principal.org_id,
            str(transaction_id),
            {"status": "Reconciled"},
        )
        payee = existing.get("payee") or payee
        updated += 1
    rule = None
    if body.remember_payee and payee:
        keyword = _payee_keyword(payee)
        if keyword:
            rule = principal.store.upsert_rule(principal.org_id, keyword, str(body.account_id))
    return {"updated": updated, "rule": rule}


@router.post("", response_model=TransactionOut)
def create_transaction(body: TransactionCreate, principal: Annotated[Principal, Depends(get_principal)]):
    try:
        return insert_transaction(
            principal.store,
            org_id=principal.org_id,
            txn_date=body.date,
            account_id=body.account_id,
            description=body.description,
            payee=body.payee or body.description[:200],
            gross_amount=body.gross_amount,
            source=body.source,
            status=body.status or "Reconciled",
            business_claim_percentage=body.business_claim_percentage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{transaction_id}", response_model=TransactionOut)
def patch_transaction(
    transaction_id: UUID,
    body: TransactionPatch,
    principal: Annotated[Principal, Depends(get_principal)],
):
    existing = principal.store.get_transaction(principal.org_id, str(transaction_id))
    if not existing:
        raise HTTPException(status_code=404, detail="Transaction not found")

    gross = body.gross_amount if body.gross_amount is not None else existing["gross_amount"]
    account_id = body.account_id or (UUID(existing["account_id"]) if existing.get("account_id") else None)
    if account_id is None:
        raise HTTPException(status_code=400, detail="Choose an account before reconciling")
    try:
        updated = recalc_transaction(
            principal.store,
            principal.org_id,
            str(transaction_id),
            account_id,
            gross,
            body.business_claim_percentage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    patch = {}
    if body.date:
        patch["date"] = body.date.isoformat()
    if body.description is not None:
        patch["description"] = body.description
    if body.payee is not None:
        patch["payee"] = body.payee
    if body.status:
        patch["status"] = body.status
    if patch:
        updated = principal.store.update_transaction(principal.org_id, str(transaction_id), patch)
    return updated


def _payee_keyword(payee: str) -> str:
    key = normalize_party(payee)[:120]
    if not key or key == "UNKNOWN PAYEE":
        return ""
    return key


def _similar(
    principal: Principal, payee: str, direction: str, exclude: str | None, start: date | None, end: date | None
) -> list[dict]:
    key = _payee_keyword(payee)
    if not key:
        return []
    rows = principal.store.list_transactions(principal.org_id, status="Pending_Review", start=start, end=end, limit=1000)
    matched = []
    for row in rows:
        if exclude and str(row["transaction_id"]) == exclude:
            continue
        if row.get("is_internal_transfer"):
            continue
        if _payee_keyword(row.get("payee") or "") != key:
            continue
        incoming = Decimal(str(row["gross_amount"])) > 0
        if direction == "in" and not incoming:
            continue
        if direction == "out" and incoming:
            continue
        matched.append(row)
    return matched
