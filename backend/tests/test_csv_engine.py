from decimal import Decimal

from app.services.csv_engine import (
    ColumnMapping,
    assign_hashes,
    classify_rows,
    compile_transfer_pattern,
    mark_transfers,
    parse_transactions,
    read_headers_and_rows,
    suggest_mapping,
)

SAMPLE = """Date,Amount,Payee,Particulars,Reference
01/10/2026,5750.00,Acme Consulting,October retainer,INV-1042
02/10/2026,-64.50,Z Energy Papamoa,Fuel,CARD
02/10/2026,-64.50,TFR 06-0492-0123456-00,To savings,TFR
03/10/2026,64.50,TRANSFER FROM CHEQUE,From everyday,TFR
04/10/2026,-22.99,Adobe Systems,Subscription,ADOBE
05/10/2026,-115.00,Countdown Tauranga,Groceries,POS
"""


def _parsed():
    headers, rows = read_headers_and_rows(SAMPLE)
    mapping_raw = suggest_mapping(headers)
    mapping = ColumnMapping(
        date=mapping_raw["date"],
        amount=mapping_raw["amount"],
        payee=mapping_raw["payee"],
        reference=mapping_raw["reference"],
        description=mapping_raw["description"],
    )
    parsed, errors = parse_transactions(rows, mapping)
    assert errors == []
    mark_transfers(parsed, compile_transfer_pattern(""))
    return parsed


def test_suggestion_maps_standard_columns():
    headers, _rows = read_headers_and_rows(SAMPLE)
    mapping = suggest_mapping(headers)
    assert mapping["date"] == "Date"
    assert mapping["amount"] == "Amount"
    assert mapping["payee"] == "Payee"


def test_transfer_pattern_does_not_capture_same_amount_fuel():
    parsed = _parsed()
    by_payee = {row.payee: row for row in parsed}
    assert by_payee["Z Energy Papamoa"].is_internal_transfer is False
    assert by_payee["Z Energy Papamoa"].gross == Decimal("-64.50")
    assert by_payee["TFR 06-0492-0123456-00"].is_internal_transfer is True
    assert by_payee["TRANSFER FROM CHEQUE"].is_internal_transfer is True
    assert "contra" in by_payee["TFR 06-0492-0123456-00"].transfer_reason


def test_two_coffees_are_not_transfers():
    text = "Date,Amount,Payee\n01/10/2026,-5.50,Cafe\n01/10/2026,-5.50,Cafe\n"
    _headers, rows = read_headers_and_rows(text)
    parsed, errors = parse_transactions(rows, ColumnMapping(date="Date", amount="Amount", payee="Payee"))
    assert errors == []
    mark_transfers(parsed, compile_transfer_pattern(""))
    assert all(not row.is_internal_transfer for row in parsed)


def test_positive_is_income_and_unmapped_stays_pending():
    parsed = _parsed()
    assign_hashes(parsed)
    accounts = [
        {"account_id": "00000000-0000-4000-8000-0000000000a1", "account_name": "Consulting Fees", "account_type": "Income"},
        {"account_id": "00000000-0000-4000-8000-0000000000a2", "account_name": "Motor Vehicle", "account_type": "Expense"},
        {"account_id": "00000000-0000-4000-8000-0000000000a3", "account_name": "Computer & Software", "account_type": "Expense"},
    ]
    rules = [
        {"keyword": "CONSULT", "account_id": "00000000-0000-4000-8000-0000000000a1", "priority": 80},
        {"keyword": "Z ENERGY", "account_id": "00000000-0000-4000-8000-0000000000a2", "priority": 50},
        {"keyword": "ADOBE", "account_id": "00000000-0000-4000-8000-0000000000a3", "priority": 30},
    ]
    classify_rows(parsed, rules, accounts, confidence_threshold=0.85)
    by_payee = {row.payee: row for row in parsed}
    assert by_payee["Acme Consulting"].status == "Reconciled"
    assert by_payee["Acme Consulting"].account_name == "Consulting Fees"
    assert by_payee["Z Energy Papamoa"].status == "Reconciled"
    assert by_payee["Adobe Systems"].status == "Reconciled"
    assert by_payee["Countdown Tauranga"].status == "Pending_Review"
    assert by_payee["Countdown Tauranga"].account_id is None
    assert by_payee["TFR 06-0492-0123456-00"].status == "Ignored"
    assert len({row.import_hash for row in parsed}) == len(parsed)


def test_blank_reference_matches_and_twins_are_both_kept():
    from app.services.csv_engine import mark_duplicates

    existing = _parsed()[:2]
    existing[0].reference = ""
    incoming, errors = parse_transactions(
        read_headers_and_rows(
            "Date,Amount,Payee,Particulars,Reference\n"
            "01/10/2026,5750.00,Acme Consulting,October retainer,INV-1042\n"
            "02/10/2026,-64.50,Z Energy Papamoa,Fuel,CARD\n"
            "02/10/2026,-64.50,Z Energy Papamoa,Fuel,CARD\n"
        )[1],
        ColumnMapping(date="Date", amount="Amount", payee="Payee", reference="Reference", description="Particulars"),
    )
    assert errors == []
    skipped = mark_duplicates(incoming, existing)
    assert skipped == 2
    assert incoming[0].is_duplicate is True
    assert incoming[1].is_duplicate is True
    assert incoming[2].is_duplicate is False
