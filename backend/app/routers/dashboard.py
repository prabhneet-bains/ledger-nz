from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import Principal, get_principal
from app.services.dates import current_nz_fy
from app.services.depreciation import period_depreciation
from app.services.gst import money
from app.services.income_tax import income_tax
from app.services.pnl import aggregate
from app.services.vehicle_link import attach_vehicle_purchases

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _period(principal: Principal, start: date | None, end: date | None):
    fy_start, fy_end = current_nz_fy()
    start = start or fy_start
    end = end or fy_end
    attach_vehicle_purchases(principal.store, principal.org_id)
    rows = principal.store.transactions_in_range(principal.org_id, start, end)
    pnl, gst = aggregate(rows, start, end)
    schedule = period_depreciation(
        principal.store.list_assets(principal.org_id),
        principal.store.list_logs(principal.org_id),
        start,
        end,
    )
    claim = Decimal(schedule["total"])
    expense = Decimal(pnl["total_expense"]) + claim
    profit = Decimal(pnl["total_income"]) - expense
    pnl["total_expense"] = str(money(expense))
    pnl["net_profit"] = str(money(profit))
    pnl["income_tax"] = income_tax(profit)
    pnl["depreciation"] = schedule
    if claim:
        line = {"account_name": "Depreciation", "account_type": "Expense", "net_amount": str(money(-claim))}
        pnl["expense_lines"] = [*(pnl.get("expense_lines") or []), line]
        pnl["lines"] = [*(pnl.get("lines") or []), line]
    return pnl, gst


@router.get("/pnl")
def pnl_snapshot(
    principal: Annotated[Principal, Depends(get_principal)],
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
):
    pnl, _gst = _period(principal, start, end)
    return pnl


@router.get("/gst")
def gst_snapshot(
    principal: Annotated[Principal, Depends(get_principal)],
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
):
    _pnl, gst = _period(principal, start, end)
    return gst


@router.get("/summary")
def summary(
    principal: Annotated[Principal, Depends(get_principal)],
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
):
    fy_start, fy_end = current_nz_fy()
    start = start or fy_start
    end = end or fy_end
    pnl, gst = _period(principal, start, end)
    historical = principal.store.list_tax(principal.org_id)[:12]
    return {
        "financial_year": {"start": start.isoformat(), "end": end.isoformat()},
        "pnl": pnl,
        "gst": gst,
        "pending_review": principal.store.count_pending(principal.org_id, start, end),
        "tax_history": historical,
        "tax_trend": {
            "current_gst_to_pay": gst["gst_to_pay"],
            "current_income": pnl["total_income"],
            "history": historical,
        },
    }
