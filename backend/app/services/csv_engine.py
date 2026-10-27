"""Bank CSV parsing, column mapping, and internal-transfer detection.

Positive amounts are income. Negative amounts are expenses.
A row is an internal transfer when the payee/description/reference matches the
transfer pattern (TFR, TRANSFER, a NZ account number, and similar). Contra
pairs are recorded only between two pattern matches with the same absolute
amount on the same or adjacent day, so a fuel purchase is not swallowed by a
transfer of the same size.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from dateutil import parser as date_parser

from app.services.gst import money

DEFAULT_TRANSFER_REGEX = (
    r"\b(?:TFR|TRF|TRANSFER|FUNDS\s+TRANSFER)\b"
    r"|\b(?:TO|FROM)\s+(?:SAVINGS|CHEQUE|CHECK|ONLINE|ACCOUNT|EVERYDAY)\b"
    r"|\bOWN\s+ACCOUNT\b"
    r"|\bINTERNAL\s+TRANSFER\b"
    r"|\d{2}-\d{4}-\d{7}-\d{2,3}"
)

ALIASES: dict[str, list[str]] = {
    "date": ["date", "transaction date", "processed date", "value date", "posted date"],
    "amount": ["amount", "value", "transaction amount"],
    "payee": ["payee", "other party", "other party name", "details", "narrative", "memo", "description", "merchant", "name"],
    "reference": ["reference", "particulars", "code", "ref"],
    "debit": ["debit", "withdrawal", "money out"],
    "credit": ["credit", "deposit", "money in"],
    "description": ["particulars", "transaction details", "memo", "narrative"],
}


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (header or "").lower()).strip()


@dataclass
class ColumnMapping:
    date: str
    payee: str
    amount: str | None = None
    debit: str | None = None
    credit: str | None = None
    reference: str | None = None
    description: str | None = None

    def validate(self) -> None:
        if not self.date or not self.payee:
            raise ValueError("Map both a date column and a payee column")
        if not self.amount and not (self.debit or self.credit):
            raise ValueError("Map an amount column, or debit and credit columns")


@dataclass
class CsvRow:
    line: int
    txn_date: date
    gross: Decimal
    payee: str
    reference: str
    description: str
    regex_hit: bool = False
    is_internal_transfer: bool = False
    transfer_reason: str = ""
    account_id: str | None = None
    account_name: str | None = None
    confidence: float = 0.0
    status: str = "Pending_Review"
    category_reason: str = ""
    import_hash: str = ""
    is_duplicate: bool = False
    existing_id: str | None = None
    already_flagged: bool = False
    errors: list[str] = field(default_factory=list)


def detect_preset(headers: list[str]) -> str:
    norms = {_norm(header) for header in headers}
    if "other party" in norms:
        return "Westpac-like"
    if "unique id" in norms:
        return "ASB-like"
    if "this party account" in norms or "other party account" in norms:
        return "BNZ-like"
    if "type" in norms and "details" in norms:
        return "ANZ-like"
    return "Custom"


def suggest_mapping(headers: list[str]) -> dict[str, str | None]:
    norm_map = {_norm(header): header for header in headers}

    def pick(key: str, used: set[str]) -> str | None:
        for alias in ALIASES[key]:
            original = norm_map.get(alias)
            if original and original not in used:
                return original
        for alias in ALIASES[key]:
            for norm, original in norm_map.items():
                if original in used:
                    continue
                if alias in norm:
                    return original
        return None

    used: set[str] = set()
    mapping: dict[str, str | None] = {}
    for key in ("date", "amount", "debit", "credit", "payee", "reference", "description"):
        found = pick(key, used)
        if found:
            mapping[key] = found
            used.add(found)
        else:
            mapping[key] = None
    return mapping


def decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV must be UTF-8 or Windows-1252")


def read_headers_and_rows(text: str) -> tuple[list[str], list[dict[str, str]]]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    headers = [name.strip() for name in reader.fieldnames if name and name.strip()]
    rows: list[dict[str, str]] = []
    for raw in reader:
        cleaned = {(key or "").strip(): (value or "").strip() for key, value in raw.items() if key}
        if not any(cleaned.values()):
            continue
        rows.append(cleaned)
    return headers, rows


def parse_amount(raw: str) -> Decimal:
    text = (raw or "").strip().replace("$", "").replace(",", "").replace(" ", "")
    if not text or text in {"-", "—"}:
        return Decimal("0")
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    if text.endswith("-"):
        negative = True
        text = text[:-1]
    if text.startswith("+"):
        text = text[1:]
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Unreadable amount '{raw}'") from exc
    if negative:
        value = -abs(value)
    return money(value)


def parse_date(raw: str) -> date:
    text = (raw or "").strip()
    if not text:
        raise ValueError("Missing date")
    # ISO first so 2026-10-01 is not read as day-first.
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    parsed = date_parser.parse(text, dayfirst=True, yearfirst=False)
    return parsed.date()


def _cell(row: dict[str, str], column: str | None) -> str:
    if not column:
        return ""
    return (row.get(column) or "").strip()


def parse_transactions(rows: list[dict[str, str]], mapping: ColumnMapping, limit: int = 5000) -> tuple[list[CsvRow], list[dict]]:
    mapping.validate()
    if len(rows) > limit:
        raise ValueError(f"CSV exceeds {limit} data rows")
    parsed: list[CsvRow] = []
    errors: list[dict] = []
    for index, raw in enumerate(rows, start=2):
        try:
            if mapping.amount:
                gross = parse_amount(_cell(raw, mapping.amount))
            else:
                debit = parse_amount(_cell(raw, mapping.debit)) if mapping.debit else Decimal("0")
                credit = parse_amount(_cell(raw, mapping.credit)) if mapping.credit else Decimal("0")
                gross = money(abs(credit) - abs(debit))
            payee = _cell(raw, mapping.payee)[:200]
            reference = _cell(raw, mapping.reference)[:200]
            extra = _cell(raw, mapping.description)[:500]
            description = " | ".join(part for part in (payee, extra, reference) if part)
            parsed.append(
                CsvRow(
                    line=index,
                    txn_date=parse_date(_cell(raw, mapping.date)),
                    gross=gross,
                    payee=payee or "Unknown payee",
                    reference=reference,
                    description=description or payee or "Bank transaction",
                )
            )
        except ValueError as exc:
            errors.append({"line": index, "error": str(exc)})
    return parsed, errors


WEAK_TRANSFER_RE = re.compile(r"\b(?:GST|TAX)\b", re.IGNORECASE)
DEFAULT_OWN_LABELS = ("SAVINGS", "TRANSACTIONS")


def normalize_party(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").upper()).strip()


def row_text(row: CsvRow) -> str:
    return f"{row.payee} {row.reference} {row.description}"


def is_strong_transfer(row: CsvRow, pattern: re.Pattern[str], labels: tuple[str, ...] | list[str]) -> bool:
    text = row_text(row)
    if pattern.search(text):
        return True
    folded = text.upper()
    for label in labels:
        token = label.strip().upper()
        if token and re.search(rf"\b{re.escape(token)}\b", folded):
            return True
    return False


def is_weak_transfer(row: CsvRow) -> bool:
    return bool(WEAK_TRANSFER_RE.search(row_text(row)))


def _can_pair(left: CsvRow, right: CsvRow, window_days: int) -> bool:
    if left.gross == 0 or right.gross == 0:
        return False
    if money(abs(left.gross)) != money(abs(right.gross)):
        return False
    if (left.gross > 0) == (right.gross > 0):
        return False
    return abs((left.txn_date - right.txn_date).days) <= window_days


def _pair(left: CsvRow, right: CsvRow) -> None:
    left.is_internal_transfer = True
    right.is_internal_transfer = True
    left.transfer_reason = f"contra own-account transfer {right.txn_date.isoformat()}"
    right.transfer_reason = f"contra own-account transfer {left.txn_date.isoformat()}"


def mark_transfers(
    rows: list[CsvRow],
    pattern: re.Pattern[str],
    labels: tuple[str, ...] | list[str] | None = None,
    window_days: int = 3,
    existing: list[CsvRow] | None = None,
) -> list[CsvRow]:
    """Flag transfers inside this file and against rows already in the ledger.

    Strong rows (transfer wording, an own-account label such as SAVINGS or
    TRANSACTIONS, or a bank account number) are ignored even when the other
    account is not in this file. GST and TAX lines are only treated as
    transfers when an opposite amount pairs with them, so an IRD payment is
    left as a real expense. A fuel purchase of the same amount is not paired
    unless that purchase itself looks like a transfer.
    """
    own_labels = labels if labels is not None else DEFAULT_OWN_LABELS
    for row in rows:
        row.regex_hit = is_strong_transfer(row, pattern, own_labels)
        if row.regex_hit:
            row.is_internal_transfer = True
            row.transfer_reason = "transfer between own accounts"
        else:
            row.is_internal_transfer = False
            row.transfer_reason = ""

    def signal(row: CsvRow) -> bool:
        return row.is_internal_transfer or row.regex_hit or is_weak_transfer(row) or is_strong_transfer(row, pattern, own_labels)

    def attempt(left: CsvRow, right: CsvRow) -> bool:
        if not _can_pair(left, right, window_days):
            return False
        if not (signal(left) and signal(right)):
            return False
        left_strong = left.regex_hit or is_strong_transfer(left, pattern, own_labels)
        right_strong = right.regex_hit or is_strong_transfer(right, pattern, own_labels)
        if not (left_strong or right_strong or (is_weak_transfer(left) and is_weak_transfer(right))):
            return False
        _pair(left, right)
        return True

    used: set[int] = set()
    for i, left in enumerate(rows):
        if i in used or not signal(left):
            continue
        for j in range(i + 1, len(rows)):
            if j in used:
                continue
            if attempt(left, rows[j]):
                used.add(i)
                used.add(j)
                break

    updated: list[CsvRow] = []
    used_existing: set[int] = set()
    for left in rows:
        if "contra own-account transfer" in left.transfer_reason:
            continue
        if not signal(left):
            continue
        for index, right in enumerate(existing or []):
            if index in used_existing:
                continue
            if attempt(left, right):
                used_existing.add(index)
                if right.existing_id and not right.already_flagged:
                    updated.append(right)
                break
    return updated


def same_bank_line(left: CsvRow, right: CsvRow) -> bool:
    """True when two statement lines are the same bank movement.

    Reference is ignored when either side is blank, so a partial export still
    matches the same line on a later full-year export.
    """
    if left.txn_date != right.txn_date:
        return False
    if money(left.gross) != money(right.gross):
        return False
    if normalize_party(left.payee) != normalize_party(right.payee):
        return False
    left_ref = normalize_party(left.reference)
    right_ref = normalize_party(right.reference)
    if left_ref and right_ref and left_ref != right_ref:
        return False
    return True


def mark_duplicates(incoming: list[CsvRow], existing: list[CsvRow]) -> int:
    pool = list(existing)
    skipped = 0
    for row in incoming:
        match_at = next((index for index, prev in enumerate(pool) if same_bank_line(row, prev)), None)
        if match_at is None:
            row.is_duplicate = False
            continue
        prev = pool.pop(match_at)
        row.is_duplicate = True
        row.is_internal_transfer = prev.is_internal_transfer
        row.transfer_reason = prev.transfer_reason
        skipped += 1
    return skipped


def ledger_row_to_csv(row: dict) -> CsvRow:
    meta = row.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta or "{}")
        except json.JSONDecodeError:
            meta = {}
    reference = str((meta or {}).get("reference") or row.get("reference") or "")
    raw_date = row.get("date")
    txn_date = raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date)[:10])
    return CsvRow(
        line=0,
        txn_date=txn_date,
        gross=Decimal(str(row.get("gross_amount") or "0")),
        payee=row.get("payee") or "",
        reference=reference,
        description=row.get("description") or "",
        existing_id=row.get("transaction_id"),
        already_flagged=bool(row.get("is_internal_transfer")),
        is_internal_transfer=bool(row.get("is_internal_transfer")),
    )


def assign_hashes(rows: list[CsvRow]) -> None:
    seen: dict[tuple, int] = {}
    for row in rows:
        key = (row.txn_date.isoformat(), str(row.gross), row.payee.upper(), row.reference.upper())
        seen[key] = seen.get(key, 0) + 1
        payload = f"{key[0]}|{key[1]}|{key[2]}|{key[3]}|{seen[key]}"
        row.import_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()


def classify_rows(
    rows: list[CsvRow],
    rules: list[dict],
    accounts: list[dict],
    *,
    confidence_threshold: float,
) -> None:
    from app.services.categorizer import match_account

    by_id = {str(account["account_id"]): account for account in accounts}
    for row in rows:
        if row.is_internal_transfer:
            row.account_id = None
            row.account_name = None
            row.confidence = 1.0
            row.status = "Ignored"
            row.category_reason = row.transfer_reason or "internal transfer"
            continue
        text = f"{row.payee} {row.description} {row.reference}"
        matched = match_account(text, rules)
        if matched is None:
            row.account_id = None
            row.account_name = None
            row.confidence = 0.4
            row.status = "Pending_Review"
            row.category_reason = "no keyword match"
            continue
        account = by_id.get(str(matched))
        row.account_id = str(matched)
        row.account_name = account["account_name"] if account else None
        account_type = account["account_type"] if account else None
        sign_conflict = (row.gross < 0 and account_type == "Income") or (row.gross > 0 and account_type == "Expense")
        if sign_conflict:
            row.confidence = 0.55
            row.status = "Pending_Review"
            row.category_reason = "keyword matched the opposite sign"
            continue
        row.confidence = 0.95
        row.status = "Reconciled" if row.confidence >= confidence_threshold else "Pending_Review"
        row.category_reason = f"keyword → {row.account_name}"


def compile_transfer_pattern(expression: str | None) -> re.Pattern[str]:
    return re.compile(expression.strip() if expression and expression.strip() else DEFAULT_TRANSFER_REGEX, re.IGNORECASE)
