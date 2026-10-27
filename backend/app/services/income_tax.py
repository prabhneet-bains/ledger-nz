from decimal import Decimal

from app.services.gst import money

# Individual rates applying from 1 April 2025, including the 2026–27 income year.
# https://www.ird.govt.nz/income-tax/income-tax-for-individuals/tax-codes-and-tax-rates-for-individuals/tax-rates-for-individuals
BRACKETS: list[tuple[Decimal | None, Decimal, str]] = [
    (Decimal("15600"), Decimal("0.105"), "10.5% to $15,600"),
    (Decimal("53500"), Decimal("0.175"), "17.5% to $53,500"),
    (Decimal("78100"), Decimal("0.300"), "30% to $78,100"),
    (Decimal("180000"), Decimal("0.330"), "33% to $180,000"),
    (None, Decimal("0.390"), "39% over $180,000"),
]


def income_tax(taxable_profit: Decimal) -> dict:
    """Progressive IRD individual tax on this practice's taxable profit.

    This is the profit in the ledger only. It leaves out salary, ACC, and tax credits.
    """
    profit = Decimal(taxable_profit)
    if profit < 0:
        profit = Decimal("0")
    bands = []
    tax = Decimal("0")
    previous = Decimal("0")
    for cap, rate, label in BRACKETS:
        upper = profit if cap is None else min(profit, cap)
        portion = upper - previous
        if portion < 0:
            portion = Decimal("0")
        slice_tax = money(portion * rate) if portion else Decimal("0.00")
        tax += slice_tax
        if portion:
            bands.append(
                {
                    "label": label,
                    "rate": str(money(rate * Decimal("100"))),
                    "income": str(money(portion)),
                    "tax": str(slice_tax),
                }
            )
        if cap is None or profit <= cap:
            break
        previous = cap
    tax = money(tax)
    return {
        "taxable_profit": str(money(Decimal(taxable_profit))),
        "income_tax": str(tax),
        "profit_after_tax": str(money(Decimal(taxable_profit) - tax)),
        "bands": bands,
        "rates_from": "2025-04-01",
    }
