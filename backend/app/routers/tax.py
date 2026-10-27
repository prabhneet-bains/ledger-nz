from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import Principal, get_principal
from app.schemas import TaxRecordCreate

router = APIRouter(prefix="/tax", tags=["tax"])


@router.get("/history")
def history(principal: Annotated[Principal, Depends(get_principal)]):
    return principal.store.list_tax(principal.org_id)


@router.post("/history")
def add_history(body: TaxRecordCreate, principal: Annotated[Principal, Depends(get_principal)]):
    if body.end_date < body.start_date:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")
    return principal.store.insert_tax(
        {
            "org_id": principal.org_id,
            "period_type": body.period_type,
            "start_date": body.start_date.isoformat(),
            "end_date": body.end_date.isoformat(),
            "total_income": body.total_income,
            "tax_paid": body.tax_paid,
            "notes": body.notes,
        }
    )
