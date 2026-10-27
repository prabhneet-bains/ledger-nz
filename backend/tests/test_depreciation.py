from datetime import date
from decimal import Decimal

from app.services.depreciation import asset_position, months_held, statutory_rate


def test_part_month_counts_as_a_whole_month():
    assert months_held(date(2026, 5, 20), date(2026, 4, 1), date(2027, 3, 31)) == 11
    assert months_held(date(2026, 4, 1), date(2026, 4, 1), date(2027, 3, 31)) == 12


def test_passenger_vehicle_uses_the_statutory_rates():
    assert statutory_rate("passenger_vehicle", "Diminishing_Value") == Decimal("30")
    assert statutory_rate("passenger_vehicle", "Straight_Line") == Decimal("21")


def test_private_use_reduces_the_claim_and_not_the_tax_value():
    asset = {
        "original_cost": "30000.00",
        "purchase_date": "2026-04-01",
        "depreciation_method": "Diminishing_Value",
        "depreciation_rate": "99",
        "asset_class": "passenger_vehicle",
        "business_use_percentage": "85",
    }
    year_one = asset_position(asset, [], date(2026, 4, 1), date(2027, 3, 31))
    assert year_one["depreciation_rate"] == "30.00"
    assert year_one["depreciation_claim"] == "7650.00"
    assert year_one["adjusted_tax_value"] == "21000.00"

    year_two = asset_position(asset, [], date(2027, 4, 1), date(2028, 3, 31))
    assert year_two["depreciation_claim"] == "5355.00"
    assert year_two["adjusted_tax_value"] == "14700.00"


def test_may_purchase_is_eleven_months():
    asset = {
        "original_cost": "30000.00",
        "purchase_date": "2026-05-20",
        "depreciation_method": "Diminishing_Value",
        "asset_class": "passenger_vehicle",
        "business_use_percentage": "100",
    }
    position = asset_position(asset, [], date(2026, 4, 1), date(2027, 3, 31))
    assert position["months"] == 11
    assert position["depreciation_claim"] == "8250.00"


def test_logbook_replaces_the_entered_vehicle_percentage():
    asset = {
        "original_cost": "10000.00",
        "purchase_date": "2026-04-01",
        "depreciation_method": "Diminishing_Value",
        "asset_class": "passenger_vehicle",
        "business_use_percentage": "100",
    }
    logs = [
        {"date": "2026-06-01", "distance": 80, "purpose": "Business"},
        {"date": "2026-09-01", "distance": 20, "purpose": "Personal"},
    ]
    position = asset_position(asset, logs, date(2026, 4, 1), date(2027, 3, 31))
    assert position["business_use_source"] == "logbook"
    assert position["business_use_percentage"] == "80.00"
    assert position["depreciation_claim"] == "2400.00"


def test_short_logbook_does_not_replace_the_entered_percentage():
    asset = {
        "original_cost": "10000.00",
        "purchase_date": "2026-04-01",
        "depreciation_method": "Diminishing_Value",
        "asset_class": "passenger_vehicle",
        "business_use_percentage": "80",
    }
    logs = [
        {"date": "2026-10-19", "distance": 42, "purpose": "Business"},
        {"date": "2026-10-20", "distance": 38, "purpose": "Personal"},
    ]
    position = asset_position(asset, logs, date(2026, 4, 1), date(2027, 3, 31))
    assert position["business_use_source"] == "entered"
    assert position["business_use_percentage"] == "80.00"
    assert position["depreciation_claim"] == "2400.00"


def test_low_value_asset_is_deducted_once():
    asset = {
        "original_cost": "800.00",
        "purchase_date": "2026-08-01",
        "depreciation_method": "Diminishing_Value",
        "depreciation_rate": "30",
        "asset_class": "other",
        "business_use_percentage": "100",
    }
    first = asset_position(asset, [], date(2026, 4, 1), date(2027, 3, 31))
    assert first["low_value_writeoff"] is True
    assert first["depreciation_claim"] == "800.00"
    later = asset_position(asset, [], date(2027, 4, 1), date(2028, 3, 31))
    assert later["depreciation_claim"] == "0.00"
