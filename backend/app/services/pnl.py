from datetime import date
from decimal import Decimal

from app.services.gst import money
from app.services.income_tax import income_tax


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


def aggregate(rows: list[dict], start: date, end: date) -> tuple[dict, dict]:
    """P&L and GST from signed ledger rows.

    Internal transfers and Ignored rows are excluded.
    Expense GST is stored negative; input GST is reported as a positive claim.
    GST_to_Pay = output GST - input GST.
    """
    grouped: dict[tuple[str, str], Decimal] = {}
    income = Decimal("0")
    expense_signed = Decimal("0")
    output_gst = Decimal("0")
    expense_gst_signed = Decimal("0")
    transfers = 0
    uncoded_count = 0
    uncoded_gross = Decimal("0")
    private_excluded = Decimal("0")
    drawings = Decimal("0")
    funds_introduced = Decimal("0")

    for row in rows:
        if row.get("is_internal_transfer") or row.get("status") == "Ignored":
            transfers += 1
            continue
        gross = _dec(row.get("gross_amount"))
        if not row.get("account_id"):
            uncoded_count += 1
            uncoded_gross += gross
            continue
        account_type = row.get("account_type") or "Expense"
        name = row.get("account_name") or "Uncategorised"
        net = _dec(row.get("net_amount"))
        gst = _dec(row.get("gst_amount"))
        grouped[(account_type, name)] = grouped.get((account_type, name), Decimal("0")) + net
        if account_type == "Income":
            income += net
            output_gst += gst
        elif account_type == "Expense":
            expense_signed += net
            expense_gst_signed += gst
            private_excluded += gross - net - gst
        elif account_type == "Asset":
            expense_gst_signed += gst
        elif name == "Drawings":
            drawings += gross
        elif name == "Owner Equity":
            funds_introduced += gross

    lines = [
        {"account_name": name, "account_type": account_type, "net_amount": str(money(amount))}
        for (account_type, name), amount in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1]))
    ]
    input_gst = -expense_gst_signed
    taxable_profit = income + expense_signed
    tax = income_tax(taxable_profit)
    pnl = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "lines": lines,
        "income_lines": [line for line in lines if line["account_type"] == "Income"],
        "expense_lines": [line for line in lines if line["account_type"] == "Expense"],
        "total_income": str(money(income)),
        "total_expense": str(money(-expense_signed)),
        "net_profit": str(money(taxable_profit)),
        "private_excluded": str(money(-private_excluded)),
        "drawings": str(money(-drawings)),
        "funds_introduced": str(money(funds_introduced)),
        "income_tax": tax,
        "transfers_excluded": transfers,
        "uncoded_count": uncoded_count,
        "uncoded_gross": str(money(uncoded_gross)),
    }
    gst = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "output_gst": str(money(output_gst)),
        "input_gst": str(money(input_gst)),
        "gst_to_pay": str(money(output_gst - input_gst)),
    }
    return pnl, gst


def profit_and_loss(store, org_id: str, start: date, end: date) -> dict:
    pnl, _gst = aggregate(store.transactions_in_range(org_id, start, end), start, end)
    return pnl


def gst_schedule(store, org_id: str, start: date, end: date) -> dict:
    _pnl, gst = aggregate(store.transactions_in_range(org_id, start, end), start, end)
    return gst
