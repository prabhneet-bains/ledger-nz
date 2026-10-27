from decimal import Decimal, ROUND_HALF_UP

TWOPLACE = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(TWOPLACE, rounding=ROUND_HALF_UP)


def gst_on_insert(
    gross_amount: Decimal,
    tax_rate: Decimal,
    business_claim_percentage: Decimal,
) -> tuple[Decimal, Decimal]:
    """IRD-style inclusive GST, scaled by business-use percentage.

    gst_amount = (gross * (rate / (100 + rate))) * (claim / 100)
    The deductible net is the business-use share excluding that GST.
    A 100% claim keeps net = gross - gst.
    """
    gross = Decimal(gross_amount)
    rate = Decimal(tax_rate)
    claim = min(max(Decimal(business_claim_percentage), Decimal("0")), Decimal("100"))

    if rate <= 0:
        gst = Decimal("0")
    else:
        gst = gross * (rate / (Decimal("100") + rate)) * (claim / Decimal("100"))

    gst = money(gst)
    business_gross = gross if claim >= 100 else money(gross * claim / Decimal("100"))
    net = money(business_gross - gst)
    return gst, net
