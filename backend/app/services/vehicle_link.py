"""Move a vehicle's purchase payments out of expenses once the car is on the asset register.

The depreciable cost is GST-exclusive. A deposit and the dealer balance that add up
to that cost are both capital, so neither remains a Motor Vehicle expense.
"""

from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations

from app.services.gst import money
from app.services.ledger import recalc_transaction


def _day(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _ex_gst(gross) -> Decimal:
    return money(abs(Decimal(str(gross))) * Decimal("100") / Decimal("115"))


def _best_purchase(candidates: list[dict], cost: Decimal) -> list[dict]:
    if not candidates:
        return []
    best: tuple[Decimal, list[dict]] | None = None
    pool = candidates[:12]
    for size in range(1, min(4, len(pool)) + 1):
        for combo in combinations(pool, size):
            total = sum((_ex_gst(row["gross_amount"]) for row in combo), Decimal("0"))
            diff = abs(total - cost)
            if best is None or diff < best[0]:
                best = (diff, list(combo))
    if best is None:
        return []
    diff, combo = best
    close = diff <= Decimal("1.00") or (len(combo) == 1 and diff <= max(Decimal("50"), cost * Decimal("0.02")))
    return combo if close else []


def attach_vehicle_purchases(store, org_id: str) -> int:
    """Recode dealer payments that belong to a passenger vehicle onto the asset account."""
    assets = [row for row in store.list_assets(org_id) if (row.get("asset_class") or "") == "passenger_vehicle"]
    if not assets:
        return 0
    accounts = store.list_accounts(org_id)
    asset_account = next((row for row in accounts if row["account_name"] == "Motor Vehicles"), None)
    if asset_account is None:
        return 0
    earliest = min(_day(row["purchase_date"]) for row in assets) - timedelta(days=31)
    latest = max(_day(row["purchase_date"]) for row in assets) + timedelta(days=31)
    rows = store.transactions_in_range(org_id, earliest, latest)
    expenses = [
        row
        for row in rows
        if row.get("account_name") == "Motor Vehicle"
        and row.get("account_type") == "Expense"
        and row.get("status") != "Ignored"
        and not row.get("is_internal_transfer")
        and row.get("transaction_id")
    ]
    used: set[str] = set()
    linked = 0
    for asset in assets:
        cost = Decimal(str(asset["original_cost"]))
        purchase = _day(asset["purchase_date"])
        candidates = [
            row
            for row in expenses
            if row["transaction_id"] not in used and abs((_day(row["date"]) - purchase).days) <= 31
        ]
        chosen = _best_purchase(candidates, cost)
        if not chosen:
            continue
        claim = Decimal(str(asset.get("business_use_percentage") or "100"))
        paid_on = min(_day(row["date"]) for row in chosen)
        for row in chosen:
            recalc_transaction(
                store,
                org_id,
                str(row["transaction_id"]),
                asset_account["account_id"],
                Decimal(str(row["gross_amount"])),
                claim,
            )
            store.update_transaction(org_id, str(row["transaction_id"]), {"status": "Reconciled"})
            used.add(str(row["transaction_id"]))
            linked += 1
        if paid_on != purchase:
            store.update_asset(org_id, str(asset["asset_id"]), {"purchase_date": paid_on.isoformat()})
    return linked
