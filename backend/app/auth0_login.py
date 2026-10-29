"""Auth0 access-token checks and first-login provisioning.

The browser sends an Auth0 access token. This module verifies it, then links
the Auth0 subject to a ledger profile. Database calls still use a short-lived
Supabase user token so row level security keeps applying. The service role is
used only to create that first link.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import httpx
import jwt
from fastapi import HTTPException, status
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import service_client
from app.localdb import ensure_local_auth0_user

logger = logging.getLogger(__name__)

EMAIL_CLAIM = "https://ledger.nz/email"
VERIFIED_CLAIM = "https://ledger.nz/email_verified"
NAME_CLAIM = "https://ledger.nz/name"
_UNAUTHORIZED = status.HTTP_401_UNAUTHORIZED


@lru_cache
def auth0_jwks_client(host: str) -> PyJWKClient:
    return PyJWKClient(f"https://{host}/.well-known/jwks.json", cache_keys=True, timeout=10)


def auth0_issuer_matches(issuer: str, settings: Settings) -> bool:
    expected = settings.auth0_issuer
    if not expected or not issuer:
        return False
    return issuer.rstrip("/") == expected.rstrip("/")


def unverified_issuer(token: str) -> str:
    try:
        claims = jwt.decode(
            token,
            options={"verify_signature": False, "verify_aud": False, "verify_exp": False},
        )
    except jwt.PyJWTError:
        return ""
    return str(claims.get("iss") or "")


def _unauthorized(exc: Exception | None = None) -> HTTPException:
    if exc is None:
        return HTTPException(status_code=_UNAUTHORIZED, detail="Invalid token")
    return HTTPException(status_code=_UNAUTHORIZED, detail="Invalid token")


def _audience_values(raw: str) -> list[str]:
    values: list[str] = []
    for part in raw.split(","):
        value = part.strip().strip('"').strip("'")
        if not value:
            continue
        for candidate in (value, value.rstrip("/"), value.rstrip("/") + "/"):
            if candidate and candidate not in values:
                values.append(candidate)
    return values


def decode_auth0_token(token: str, settings: Settings, *, audience: str | None = None) -> dict:
    if not settings.auth0_host:
        raise _unauthorized()
    expected_audience = audience if audience is not None else settings.auth0_audience.strip()
    audiences = _audience_values(expected_audience)
    if not audiences:
        raise _unauthorized()
    if token.count(".") != 2:
        # Opaque Auth0 tokens appear when the SPA refresh grant omitted the API audience.
        raise HTTPException(
            status_code=_UNAUTHORIZED,
            detail="Auth0 access token is not a JWT. Sign out and sign in again.",
        )
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise _unauthorized(exc) from exc
    if header.get("alg") != "RS256":
        raise _unauthorized()
    try:
        signing_key = auth0_jwks_client(settings.auth0_host).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=audiences if len(audiences) > 1 else audiences[0],
            issuer=[settings.auth0_issuer, settings.auth0_issuer.rstrip("/")],
            leeway=10,
        )
        return claims
    except jwt.PyJWTError as exc:
        logger.warning("Auth0 token rejected: %s", exc)
        raise _unauthorized(exc) from exc


def _as_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
    return None


def profile_from_claims(claims: dict) -> tuple[str, str, bool | None]:
    email = str(claims.get(EMAIL_CLAIM) or claims.get("email") or "").strip().lower()
    name = str(claims.get(NAME_CLAIM) or claims.get("name") or "").strip()
    verified = _as_bool(claims.get(VERIFIED_CLAIM))
    if verified is None:
        verified = _as_bool(claims.get("email_verified"))
    return email, name, verified


def _fill_profile(email: str, name: str, verified: bool | None, claims: dict) -> tuple[str, str, bool | None]:
    next_email, next_name, next_verified = profile_from_claims(claims)
    return email or next_email, name or next_name, verified if verified is not None else next_verified


def _userinfo(access_token: str, settings: Settings) -> dict:
    try:
        response = httpx.get(
            f"https://{settings.auth0_host}/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
            follow_redirects=False,
        )
    except httpx.HTTPError:
        return {}
    if response.status_code != 200:
        return {}
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def resolve_auth0_profile(claims: dict, access_token: str, id_token: str | None, settings: Settings) -> tuple[str, str]:
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise _unauthorized()
    email, name, verified = profile_from_claims(claims)
    if id_token and settings.auth0_client_id.strip() and (not email or verified is None):
        if len(id_token) > 12000:
            raise _unauthorized()
        id_claims = decode_auth0_token(id_token, settings, audience=settings.auth0_client_id.strip())
        if id_claims.get("sub") != subject:
            raise _unauthorized()
        azp = id_claims.get("azp")
        if azp and azp != settings.auth0_client_id.strip():
            raise _unauthorized()
        email, name, verified = _fill_profile(email, name, verified, id_claims)
    if not email or verified is None:
        email, name, verified = _fill_profile(email, name, verified, _userinfo(access_token, settings))
    if not email or verified is not True:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Auth0 did not provide a verified email address")
    if not name:
        name = email.split("@", 1)[0]
    return email, name


def assert_verified_claim(claims: dict) -> None:
    verified = profile_from_claims(claims)[2]
    if verified is False:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verify your email address before opening the ledger")


def bind_local_auth0(
    session: Session,
    claims: dict,
    access_token: str,
    id_token: str | None,
    settings: Settings,
) -> str:
    from app.models import AuthIdentity

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise _unauthorized()
    assert_verified_claim(claims)
    identity = session.get(AuthIdentity, ("auth0", subject))
    if identity:
        return identity.user_id
    email, name = resolve_auth0_profile(claims, access_token, id_token, settings)
    return ensure_local_auth0_user(session, subject, email, name)


def _identity_user_id(client, subject: str) -> str | None:
    result = (
        client.table("auth_identities")
        .select("user_id")
        .eq("provider", "auth0")
        .eq("subject", subject)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return None
    return str(rows[0]["user_id"])


def _profile_id_by_email(client, email: str) -> str | None:
    result = client.table("profiles").select("id").eq("email", email).limit(1).execute()
    rows = result.data or []
    if not rows:
        return None
    return str(rows[0]["id"])


def _already_registered(exc: Exception) -> bool:
    text = str(exc).lower()
    return "already" in text or "registered" in text or "exists" in text


def _insert_identity(client, subject: str, user_id: str, email: str) -> str:
    try:
        client.table("auth_identities").insert(
            {"provider": "auth0", "subject": subject, "user_id": user_id, "email": email}
        ).execute()
    except Exception as exc:
        existing = _identity_user_id(client, subject)
        if existing:
            return existing
        logger.exception("Auth0 identity link failed")
        raise HTTPException(status_code=502, detail="Could not link the Auth0 user") from exc
    return user_id


def supabase_user_for_auth0(client, subject: str, email: str, full_name: str) -> str:
    existing = _identity_user_id(client, subject)
    if existing:
        return existing
    normalised = email.strip().lower()
    display = full_name.strip() or normalised.split("@", 1)[0]
    try:
        created = client.auth.admin.create_user(
            {
                "email": normalised,
                "email_confirm": True,
                "user_metadata": {"full_name": display},
            }
        )
    except Exception as exc:
        if not _already_registered(exc):
            logger.exception("Auth0 provisioning failed")
            raise HTTPException(status_code=502, detail="Could not provision the ledger account") from exc
        user_id = _profile_id_by_email(client, normalised)
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email is already registered and is not linked to a practice",
            ) from exc
    else:
        user = getattr(created, "user", None)
        user_id = str(getattr(user, "id", "") or "")
        if not user_id:
            raise HTTPException(status_code=502, detail="Could not provision the ledger account")
    linked = _insert_identity(client, subject, user_id, normalised)
    logger.info("Linked Auth0 subject to ledger user %s", linked)
    return linked


def bind_supabase_auth0(claims: dict, access_token: str, id_token: str | None, settings: Settings) -> tuple[str, str]:
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise _unauthorized()
    assert_verified_claim(claims)
    if not settings.supabase_service_role_key.strip():
        raise HTTPException(status_code=500, detail="Auth0 provisioning needs SUPABASE_SERVICE_ROLE_KEY")
    client = service_client()
    existing = _identity_user_id(client, subject)
    if existing:
        return existing, ""
    email, name = resolve_auth0_profile(claims, access_token, id_token, settings)
    return supabase_user_for_auth0(client, subject, email, name), email


def mint_supabase_user_jwt(settings: Settings, user_id: str, email: str) -> str:
    if not settings.supabase_jwt_secret:
        raise HTTPException(status_code=500, detail="JWT secret is not configured")
    now = datetime.now(timezone.utc)
    payload = {
        "aud": "authenticated",
        "exp": now + timedelta(minutes=10),
        "iat": now,
        "iss": f"{settings.supabase_url.rstrip('/')}/auth/v1",
        "sub": user_id,
        "role": "authenticated",
        "email": email,
    }
    return jwt.encode(payload, settings.supabase_jwt_secret, algorithm="HS256")
