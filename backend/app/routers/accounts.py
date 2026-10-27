from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.deps import Principal, get_principal
from app.schemas import AccountCreate, AccountOut

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountOut])
def list_accounts(principal: Annotated[Principal, Depends(get_principal)]):
    return principal.store.list_accounts(principal.org_id)


@router.post("", response_model=AccountOut)
def create_account(body: AccountCreate, principal: Annotated[Principal, Depends(get_principal)]):
    try:
        return principal.store.create_account(
            principal.org_id,
            {
                "account_name": body.account_name,
                "account_type": body.account_type,
                "tax_rate": body.tax_rate,
                "business_claim_percentage": body.business_claim_percentage,
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not create account") from exc
