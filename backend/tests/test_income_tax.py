from decimal import Decimal

from app.services.income_tax import income_tax


def test_ird_brackets_from_april_2025():
    assert income_tax(Decimal("0"))["income_tax"] == "0.00"
    assert income_tax(Decimal("-20"))["income_tax"] == "0.00"
    assert income_tax(Decimal("15600"))["income_tax"] == "1638.00"
    assert income_tax(Decimal("53500"))["income_tax"] == "8270.50"
    assert income_tax(Decimal("78100"))["income_tax"] == "15650.50"
    assert income_tax(Decimal("180000"))["income_tax"] == "49277.50"
    over = income_tax(Decimal("180001"))
    assert over["income_tax"] == "49277.89"
    assert over["bands"][-1]["label"].startswith("39%")
