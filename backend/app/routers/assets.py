from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import Principal, get_principal
from app.schemas import AssetCreate, CapitaliseVehicle
from app.services.dates import current_nz_fy
from app.services.depreciation import PRESETS, asset_position, statutory_rate
from app.services.gst import money
from app.services.ledger import recalc_transaction
from app.services.vehicle_link import attach_vehicle_purchases

router = APIRouter(prefix="/assets", tags=["assets"])


def _prepared(body: AssetCreate) -> dict:
    method = body.depreciation_method if body.depreciation_method != "Maximum_Permissible" else "Diminishing_Value"
    rate = statutory_rate(body.asset_class, method)
    if rate is None:
        rate = body.depreciation_rate
    if rate <= 0 or rate > 100:
        raise HTTPException(status_code=400, detail="Enter a depreciation rate from the IR265 guide")
    return {
        "asset_name": body.asset_name,
        "asset_class": body.asset_class if body.asset_class in PRESETS or body.asset_class == "other" else "other",
        "purchase_date": body.purchase_date.isoformat(),
        "original_cost": body.original_cost,
        "depreciation_method": method,
        "depreciation_rate": rate,
        "business_use_percentage": body.business_use_percentage,
        "accumulated_depreciation": body.accumulated_depreciation,
    }


def _with_position(row: dict, logs: list[dict], start: date, end: date) -> dict:
    row.update(asset_position(row, logs, start, end))
    return row


@router.get("/rates")
def depreciation_rates():
    return {
        "low_value_limit": "1000.00",
        "low_value_from": "2021-03-17",
        "presets": [
            {"asset_class": key, **value}
            for key, value in PRESETS.items()
        ],
    }


@router.get("")
def list_assets(
    principal: Annotated[Principal, Depends(get_principal)],
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
):
    attach_vehicle_purchases(principal.store, principal.org_id)
    fy_start, fy_end = current_nz_fy()
    start = start or fy_start
    end = end or fy_end
    logs = principal.store.list_logs(principal.org_id)
    rows = [_with_position(row, logs, start, end) for row in principal.store.list_assets(principal.org_id)]
    return {"financial_year": {"start": start.isoformat(), "end": end.isoformat()}, "assets": rows}


@router.post("")
def create_asset(body: AssetCreate, principal: Annotated[Principal, Depends(get_principal)]):
    payload = _prepared(body)
    payload["org_id"] = principal.org_id
    created = principal.store.insert_asset(payload)
    attach_vehicle_purchases(principal.store, principal.org_id)
    return created


@router.post("/capitalise")
def capitalise_vehicle(body: CapitaliseVehicle, principal: Annotated[Principal, Depends(get_principal)]):
    """Move a bank payment for a vehicle onto the asset register and out of expenses."""
    existing = principal.store.get_transaction(principal.org_id, str(body.transaction_id))
    if not existing:
        raise HTTPException(status_code=404, detail="Transaction not found")
    accounts = principal.store.list_accounts(principal.org_id)
    asset_account = next((row for row in accounts if row["account_name"] == "Motor Vehicles"), None)
    if asset_account is None:
        raise HTTPException(status_code=400, detail="Motor Vehicles asset account is missing")
    gross = abs(Decimal(str(existing["gross_amount"])))
    cost = money(gross * Decimal("100") / Decimal("115")) if body.gst_inclusive else money(gross)
    if cost <= Decimal("1000"):
        raise HTTPException(
            status_code=400,
            detail="A vehicle costing $1,000 or less (GST exclusive) is deducted in full. Code it as a Motor Vehicle expense.",
        )
    method = "Straight_Line" if body.depreciation_method == "Straight_Line" else "Diminishing_Value"
    rate = statutory_rate("passenger_vehicle", method)
    asset = principal.store.insert_asset(
        {
            "org_id": principal.org_id,
            "asset_name": (body.asset_name or existing.get("payee") or "Passenger vehicle")[:200],
            "asset_class": "passenger_vehicle",
            "purchase_date": str(existing["date"])[:10],
            "original_cost": cost,
            "depreciation_method": method,
            "depreciation_rate": rate,
            "business_use_percentage": body.business_use_percentage,
        }
    )
    try:
        transaction = recalc_transaction(
            principal.store,
            principal.org_id,
            str(body.transaction_id),
            asset_account["account_id"],
            Decimal(str(existing["gross_amount"])),
            body.business_use_percentage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    transaction = principal.store.update_transaction(
        principal.org_id,
        str(body.transaction_id),
        {"status": "Reconciled"},
    )
    return {"asset": asset, "transaction": transaction}
