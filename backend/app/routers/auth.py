from typing import Annotated

import jwt
from fastapi import APIRouter, Header, HTTPException

from app.auth0_login import auth0_issuer_matches, decode_auth0_token
from app.config import get_settings
from app.deps import issue_dev_token, local_mode

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/dev-login")
def dev_login():
    settings = get_settings()
    if settings.app_env == "production" or not settings.allow_dev_auth or not local_mode(settings):
        raise HTTPException(status_code=404, detail="Not found")
    return {"access_token": issue_dev_token(settings), "token_type": "bearer"}


@router.get("/config")
def auth_config():
    """Public Auth0 expectations so a mismatched Render env is easy to spot."""
    settings = get_settings()
    return {
        "auth0_configured": bool(settings.auth0_host and settings.auth0_audience.strip()),
        "auth0_host": settings.auth0_host or None,
        "auth0_issuer": settings.auth0_issuer or None,
        "auth0_audience": settings.auth0_audience.strip() or None,
        "auth0_client_id_set": bool(settings.auth0_client_id.strip()),
        "version": "1.2.0",
    }


@router.get("/inspect")
def inspect_token(authorization: Annotated[str | None, Header()] = None):
    """Compare the bearer token claims with what the API is configured to accept."""
    settings = get_settings()
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if token.count(".") != 2:
        return {
            "jwt": False,
            "valid": False,
            "error": "Auth0 access token is not a JWT. Sign out and sign in again.",
            "expected_issuer": settings.auth0_issuer or None,
            "expected_audience": settings.auth0_audience.strip() or None,
        }
    try:
        header = jwt.get_unverified_header(token)
        claims = jwt.decode(
            token,
            options={"verify_signature": False, "verify_aud": False, "verify_exp": False},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token ({exc})") from exc
    token_issuer = str(claims.get("iss") or "")
    token_audience = claims.get("aud")
    result = {
        "jwt": True,
        "alg": header.get("alg"),
        "token_issuer": token_issuer or None,
        "token_audience": token_audience,
        "expected_issuer": settings.auth0_issuer or None,
        "expected_audience": settings.auth0_audience.strip() or None,
        "issuer_match": auth0_issuer_matches(token_issuer, settings),
        "valid": False,
        "error": None,
    }
    try:
        decode_auth0_token(token, settings)
        result["valid"] = True
    except HTTPException as exc:
        result["error"] = exc.detail
    return result
