from decimal import Decimal

from app.services.gst import gst_on_insert


def test_standard_15_percent_inclusive():
    gst, net = gst_on_insert(Decimal("115.00"), Decimal("15.00"), Decimal("100.00"))
    assert gst == Decimal("15.00")
    assert net == Decimal("100.00")


def test_claim_percentage_keeps_the_business_portion():
    gst, net = gst_on_insert(Decimal("115.00"), Decimal("15.00"), Decimal("50.00"))
    assert gst == Decimal("7.50")
    assert net == Decimal("50.00")


def test_zero_rated():
    gst, net = gst_on_insert(Decimal("80.00"), Decimal("0"), Decimal("100"))
    assert gst == Decimal("0.00")
    assert net == Decimal("80.00")


def test_negative_expense_keeps_sign():
    gst, net = gst_on_insert(Decimal("-64.50"), Decimal("15.00"), Decimal("100"))
    assert gst == Decimal("-8.41")
    assert net == Decimal("-56.09")
