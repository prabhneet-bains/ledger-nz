"""IRD depreciation for assets acquired in the 2006 and later income years.

Passenger vehicles that carry up to 12 people, and are not on short-term hire,
use the economic rate in Income Tax Act 2007 s EE 29: 30% diminishing value or
21% straight line. IR265 (March 2026) lists the same rates. A part-month of
ownership counts as a whole month. Private use is applied after that. The
adjusted tax value still falls by the full year's depreciation, including the
private share.

Assets costing $1,000 or less (GST exclusive) from 17 March 2021 are deducted
immediately instead of depreciated.
"""

from datetime import date
from decimal import Decimal

from app.services.dates import current_nz_fy
from app.services.gst import money

LOW_VALUE_LIMIT = Decimal("1000")
LOW_VALUE_FROM = date(2021, 3, 17)

PRESETS: dict[str, dict] = {
    "passenger_vehicle": {
        "label": "Passenger vehicle (up to 12 seats)",
        "diminishing_value": "30.00",
        "straight_line": "21.00",
        "authority": "Income Tax Act 2007 s EE 29 and IR265 (March 2026)",
    },
    "computer": {
        "label": "Computer equipment",
        "diminishing_value": "50.00",
        "straight_line": "40.00",
        "authority": "IR265 (March 2026) computer equipment default class",
    },
    "office_furniture": {
        "label": "Office furniture",
        "diminishing_value": "16.00",
        "straight_line": "10.50",
        "authority": "IR265 (March 2026) office furniture default class",
    },
}


def statutory_rate(asset_class: str, method: str) -> Decimal | None:
    preset = PRESETS.get(asset_class or "")
    if not preset:
        return None
    key = "straight_line" if method == "Straight_Line" else "diminishing_value"
    return Decimal(preset[key])


def months_held(owned_from: date, period_start: date, period_end: date) -> int:
    """Calendar months in the period during which the asset was owned. A part-month counts."""
    if owned_from > period_end or period_start > period_end:
        return 0
    start = owned_from if owned_from > period_start else period_start
    year, month = start.year, start.month
    count = 0
    while (year, month) <= (period_end.year, period_end.month):
        count += 1
        month += 1
        if month == 13:
            month = 1
            year += 1
    return count


def _fy_of(day: date) -> tuple[date, date]:
    return current_nz_fy(day)


def _next_fy(start: date) -> tuple[date, date]:
    return date(start.year + 1, 4, 1), date(start.year + 2, 3, 31)


def logbook_business_use(logs: list[dict], start: date, end: date) -> Decimal | None:
    """Use the logbook once it covers a 90-day sample. A shorter record stays advisory."""
    business = 0
    total = 0
    days: list[date] = []
    for row in logs:
        raw = row.get("date")
        day = raw if isinstance(raw, date) else date.fromisoformat(str(raw)[:10])
        if day < start or day > end:
            continue
        distance = int(row.get("distance") or 0)
        total += distance
        days.append(day)
        if row.get("purpose") == "Business":
            business += distance
    if total <= 0 or not days or (max(days) - min(days)).days < 90:
        return None
    return money(Decimal(business) / Decimal(total) * Decimal("100"))


def _parse_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def asset_position(row: dict, logs: list[dict], start: date, end: date) -> dict:
    """Depreciation to claim between start and end, and the adjusted tax value at end."""
    cost = Decimal(str(row["original_cost"]))
    purchase = _parse_date(row["purchase_date"])
    method = row.get("depreciation_method") or "Diminishing_Value"
    asset_class = row.get("asset_class") or "other"
    rate = statutory_rate(asset_class, method)
    if rate is None:
        rate = Decimal(str(row.get("depreciation_rate") or "0"))
    use = Decimal(str(row.get("business_use_percentage") or "100"))
    use_source = "entered"
    if asset_class == "passenger_vehicle":
        logged = logbook_business_use(logs, start, end)
        if logged is not None:
            use = logged
            use_source = "logbook"

    low_value = cost <= LOW_VALUE_LIMIT and purchase >= LOW_VALUE_FROM
    if low_value:
        in_period = start <= purchase <= end
        claim = money(cost * use / Decimal("100")) if in_period else Decimal("0.00")
        book = Decimal("0.00") if purchase <= end else cost
        return _result(cost, rate, method, use, use_source, claim, book, 0 if not in_period else 12, True)

    opening = cost
    claim = Decimal("0.00")
    months_in_view = 0
    cursor, fy_end = _fy_of(purchase)
    guard = 0
    while cursor <= end and opening > 0 and guard < 80:
        guard += 1
        months = months_held(purchase, cursor, fy_end)
        if method == "Straight_Line":
            gross = money(cost * rate / Decimal("100") * Decimal(months) / Decimal("12"))
        else:
            gross = money(opening * rate / Decimal("100") * Decimal(months) / Decimal("12"))
        if gross > opening:
            gross = opening
        view_start = start if start > cursor else cursor
        view_end = end if end < fy_end else fy_end
        overlap = months_held(purchase, view_start, view_end) if view_start <= view_end else 0
        if months and overlap:
            deductible = money(gross * use / Decimal("100") * Decimal(overlap) / Decimal(months))
            claim += deductible
            months_in_view += overlap
        opening = money(opening - gross)
        cursor, fy_end = _next_fy(cursor)
    return _result(cost, rate, method, use, use_source, money(claim), opening, months_in_view, False)


def _result(cost, rate, method, use, use_source, claim, book, months, low_value) -> dict:
    return {
        "depreciation_rate": str(money(rate)),
        "depreciation_method": method,
        "business_use_percentage": str(money(use)),
        "business_use_source": use_source,
        "months": months,
        "depreciation_claim": str(money(claim)),
        "adjusted_tax_value": str(money(book)),
        "estimated_book_value": str(money(book)),
        "low_value_writeoff": low_value,
        "original_cost": str(money(cost)),
    }


def period_depreciation(assets: list[dict], logs: list[dict], start: date, end: date) -> dict:
    lines = []
    total = Decimal("0")
    for asset in assets:
        position = asset_position(asset, logs, start, end)
        claim = Decimal(position["depreciation_claim"])
        total += claim
        lines.append(
            {
                "asset_id": asset.get("asset_id"),
                "asset_name": asset.get("asset_name"),
                "asset_class": asset.get("asset_class") or "other",
                **position,
            }
        )
    return {"total": str(money(total)), "lines": lines}


def estimated_book_value(row: dict, as_at: date | None = None) -> Decimal:
    as_at = as_at or date.today()
    start, _end = _fy_of(_parse_date(row["purchase_date"]))
    position = asset_position(row, [], start, as_at)
    return Decimal(position["adjusted_tax_value"])
