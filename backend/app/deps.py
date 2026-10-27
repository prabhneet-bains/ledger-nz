from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Header, HTTPException, status
from jwt import PyJWKClient

from app.auth0_login import (
    auth0_issuer_matches,
    bind_local_auth0,
    bind_supabase_auth0,
    decode_auth0_token,
    mint_supabase_user_jwt,
    unverified_issuer,
)
from app.config import Settings, get_settings
from app.db import user_client
from app.localdb import DEV_USER_ID, SessionLocal
from app.store import SqlStore, SupabaseStore

DEV_JWT_SECRET = "ledger-nz-dev-only-jwt-secret"


class Principal:
    def __init__(self, user_id: str, org_id: str, token: str, store):
        self.user_id = user_id
        self.org_id = org_id
        self.token = token
        self.store = store


def local_mode(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return not (settings.supabase_url or "").strip()


def signing_secret(settings: Settings) -> str:
    if settings.supabase_jwt_secret:
        return settings.supabase_jwt_secret
    if settings.allow_dev_auth and settings.app_env != "production" and local_mode(settings):
        return DEV_JWT_SECRET
    return ""


def issue_dev_token(settings: Settings) -> str:
    secret = signing_secret(settings)
    if not secret:
        raise HTTPException(status_code=500, detail="JWT secret is not configured")
    payload = {
        "sub": DEV_USER_ID,
        "aud": "authenticated",
        "role": "authenticated",
        "exp": datetime.now(timezone.utc) + timedelta(days=30),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@lru_cache
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(f"{url.rstrip('/')}/auth/v1/.well-known/jwks.json", cache_keys=True, timeout=10)


def decode_token(token: str, settings: Settings) -> dict:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    if auth0_issuer_matches(unverified_issuer(token), settings):
        return decode_auth0_token(token, settings)
    if settings.auth0_host and settings.app_env == "production":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    algorithm = header.get("alg")
    try:
        if algorithm in {"ES256", "RS256"}:
            if not settings.supabase_url:
                raise jwt.PyJWTError("No JWKS endpoint configured")
            key = _jwks_client(settings.supabase_url).get_signing_key_from_jwt(token)
            return jwt.decode(token, key.key, algorithms=["ES256", "RS256"], audience="authenticated")
        if algorithm == "HS256":
            secret = signing_secret(settings)
            if not secret:
                raise jwt.PyJWTError("Missing HMAC secret")
            return jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unsupported token algorithm")


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def _is_auth0(payload: dict, settings: Settings) -> bool:
    return auth0_issuer_matches(str(payload.get("iss") or ""), settings)


def get_principal(
    authorization: Annotated[str | None, Header()] = None,
    x_auth0_id_token: Annotated[str | None, Header()] = None,
):
    settings = get_settings()
    token = _bearer_token(authorization)
    payload = decode_token(token, settings)
    auth0 = _is_auth0(payload, settings)

    if local_mode(settings):
        session = SessionLocal()
        try:
            if auth0:
                user_id = bind_local_auth0(session, payload, token, x_auth0_id_token, settings)
            else:
                user_id = payload.get("sub")
            if not user_id:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject")
            store = SqlStore(session)
            profile = store.get_profile(user_id)
            if not profile:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No organisation profile")
            yield Principal(user_id=user_id, org_id=profile["org_id"], token=token, store=store)
        finally:
            session.close()
        return

    if auth0:
        user_id, email = bind_supabase_auth0(payload, token, x_auth0_id_token, settings)
        store_token = mint_supabase_user_jwt(settings, user_id, email)
    else:
        user_id = payload.get("sub")
        store_token = token
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject")
    client = user_client(store_token)
    store = SupabaseStore(client)
    profile = store.get_profile(user_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No organisation profile")
    yield Principal(user_id=user_id, org_id=profile["org_id"], token=store_token, store=store)
