from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.deps import issue_dev_token, local_mode

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/dev-login")
def dev_login():
    settings = get_settings()
    if settings.app_env == "production" or not settings.allow_dev_auth or not local_mode(settings):
        raise HTTPException(status_code=404, detail="Not found")
    return {"access_token": issue_dev_token(settings), "token_type": "bearer"}
