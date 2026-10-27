import json
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.config import get_settings
from app.deps import Principal, get_principal
from app.schemas import CsvMapping
from app.services.csv_engine import (
    ColumnMapping,
    assign_hashes,
    classify_rows,
    compile_transfer_pattern,
    decode_csv,
    detect_preset,
    ledger_row_to_csv,
    mark_duplicates,
    mark_transfers,
    parse_transactions,
    read_headers_and_rows,
    suggest_mapping,
)
from app.services.ledger import insert_transaction
from app.store import DuplicateTransaction

router = APIRouter(prefix="/csv", tags=["csv"])

MAX_CSV_BYTES = 5 * 1024 * 1024


async def _load_csv(file: UploadFile) -> tuple[list[str], list[dict[str, str]]]:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV exceeds 5 MB")
    try:
        text = decode_csv(content)
        return read_headers_and_rows(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _mapping(raw: str) -> ColumnMapping:
    try:
        parsed = CsvMapping.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid column mapping: {exc}") from exc
    mapping = ColumnMapping(
        date=parsed.date,
        payee=parsed.payee,
        amount=parsed.amount,
        debit=parsed.debit,
        credit=parsed.credit,
        reference=parsed.reference,
        description=parsed.description,
    )
    try:
        mapping.validate()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return mapping


def _prepare(principal: Principal, table_rows: list[dict[str, str]], mapping: ColumnMapping):
    settings = get_settings()
    try:
        parsed, errors = parse_transactions(table_rows, mapping)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    existing = _existing_rows(principal, parsed, settings.transfer_window_days)
    mark_duplicates(parsed, existing)
    linked = mark_transfers(
        [row for row in parsed if not row.is_duplicate],
        compile_transfer_pattern(settings.transfer_regex),
        labels=settings.own_labels,
        window_days=settings.transfer_window_days,
        existing=existing,
    )
    assign_hashes(parsed)
    accounts = principal.store.list_accounts(principal.org_id)
    rules = principal.store.list_rules(principal.org_id)
    classify_rows(parsed, rules, accounts, confidence_threshold=settings.confidence_floor)
    return parsed, errors, linked


def _existing_rows(principal: Principal, parsed, window_days: int):
    if not parsed:
        return []
    start = min(row.txn_date for row in parsed) - timedelta(days=window_days)
    end = max(row.txn_date for row in parsed) + timedelta(days=window_days)
    return [ledger_row_to_csv(row) for row in principal.store.transactions_between(principal.org_id, start, end)]


def _apply_linked_transfers(principal: Principal, linked) -> None:
    for row in linked:
        if not row.existing_id:
            continue
        principal.store.update_transaction(
            principal.org_id,
            row.existing_id,
            {
                "account_id": None,
                "is_internal_transfer": True,
                "status": "Ignored",
                "gst_amount": "0.00",
                "net_amount": str(row.gross),
            },
        )


def _public_row(row) -> dict:
    return {
        "line": row.line,
        "date": row.txn_date.isoformat(),
        "payee": row.payee,
        "description": row.description,
        "gross_amount": str(row.gross),
        "account_id": row.account_id,
        "account_name": row.account_name,
        "is_internal_transfer": row.is_internal_transfer,
        "status": row.status,
        "confidence": row.confidence,
        "reason": row.category_reason,
        "is_duplicate": row.is_duplicate,
    }


def _counts(rows) -> dict:
    return {
        "row_count": len(rows),
        "ready": sum(1 for row in rows if row.status == "Reconciled"),
        "pending_review": sum(1 for row in rows if row.status == "Pending_Review"),
        "internal_transfers": sum(1 for row in rows if row.is_internal_transfer),
        "duplicates": sum(1 for row in rows if row.is_duplicate),
    }


@router.post("/preview")
async def preview_csv(principal: Annotated[Principal, Depends(get_principal)], file: UploadFile = File(...)):
    headers, rows = await _load_csv(file)
    return {
        "headers": headers,
        "preset": detect_preset(headers),
        "suggested_mapping": suggest_mapping(headers),
        "sample_rows": rows[:8],
        "row_count": len(rows),
    }


@router.post("/analyze")
async def analyze_csv(
    principal: Annotated[Principal, Depends(get_principal)],
    file: UploadFile = File(...),
    mapping: str = Form(...),
):
    _headers, rows = await _load_csv(file)
    parsed, errors, _linked = _prepare(principal, rows, _mapping(mapping))
    return {**_counts(parsed), "errors": errors, "rows": [_public_row(row) for row in parsed[:200]]}


@router.post("/import")
async def import_csv(
    principal: Annotated[Principal, Depends(get_principal)],
    file: UploadFile = File(...),
    mapping: str = Form(...),
):
    _headers, rows = await _load_csv(file)
    parsed, errors, linked = _prepare(principal, rows, _mapping(mapping))
    _apply_linked_transfers(principal, linked)
    existing = principal.store.existing_import_hashes(principal.org_id, [row.import_hash for row in parsed if row.import_hash])
    inserted = 0
    skipped = 0
    for row in parsed:
        if row.is_duplicate or row.import_hash in existing:
            skipped += 1
            continue
        try:
            insert_transaction(
                principal.store,
                org_id=principal.org_id,
                txn_date=row.txn_date,
                account_id=row.account_id,
                description=row.description,
                payee=row.payee,
                gross_amount=row.gross,
                source="CSV_Upload",
                status=row.status,
                is_internal_transfer=row.is_internal_transfer,
                import_hash=row.import_hash,
                metadata={"reason": row.category_reason, "confidence": row.confidence, "reference": row.reference},
            )
            inserted += 1
            existing.add(row.import_hash)
        except DuplicateTransaction:
            skipped += 1
    return {**_counts(parsed), "inserted": inserted, "skipped_duplicates": skipped, "errors": errors}
