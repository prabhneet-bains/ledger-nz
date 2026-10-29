import base64
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.auth0_login import decode_auth0_token, resolve_auth0_profile, supabase_user_for_auth0
from app.config import Settings, assert_production
from app.deps import decode_token
from app.localdb import DEFAULT_ACCOUNTS, ensure_local_auth0_user
from app.models import Account, AuthIdentity, Base, Profile

AUDIENCE = "https://ledger-nz-api"
ISSUER = "https://tenant.auth0.com/"
CLIENT_ID = "client-id"


def _settings(**overrides) -> Settings:
    values = {
        "app_env": "development",
        "supabase_url": "",
        "supabase_jwt_secret": "test-secret",
        "supabase_service_role_key": "service-role",
        "auth0_domain": "tenant.auth0.com",
        "auth0_audience": AUDIENCE,
        "auth0_client_id": CLIENT_ID,
        "allow_dev_auth": False,
    }
    values.update(overrides)
    return Settings(**values)


def _rsa():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


class _Jwks:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, _token):
        return SimpleNamespace(key=self._key)


def _access_token(private_key, **overrides) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "auth0|ada",
        "aud": AUDIENCE,
        "iss": ISSUER,
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "email": "ada@example.com",
        "email_verified": True,
        "name": "Ada",
    }
    payload.update(overrides)
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "test"})


def test_auth0_access_token_verifies(monkeypatch):
    private_key, public_key = _rsa()
    monkeypatch.setattr("app.auth0_login.auth0_jwks_client", lambda _host: _Jwks(public_key))
    claims = decode_auth0_token(_access_token(private_key), _settings())
    assert claims["sub"] == "auth0|ada"


def test_auth0_audience_trailing_slash_is_accepted(monkeypatch):
    private_key, public_key = _rsa()
    monkeypatch.setattr("app.auth0_login.auth0_jwks_client", lambda _host: _Jwks(public_key))
    claims = decode_auth0_token(
        _access_token(private_key),
        _settings(auth0_audience=AUDIENCE + "/"),
    )
    assert claims["sub"] == "auth0|ada"


def test_opaque_auth0_token_is_rejected_clearly():
    with pytest.raises(HTTPException) as exc:
        decode_auth0_token("opaque-access-token", _settings())
    assert exc.value.status_code == 401
    assert "not a JWT" in exc.value.detail


def test_id_token_is_rejected_as_an_api_token(monkeypatch):
    private_key, public_key = _rsa()
    monkeypatch.setattr("app.auth0_login.auth0_jwks_client", lambda _host: _Jwks(public_key))
    token = _access_token(private_key, aud=CLIENT_ID)
    with pytest.raises(HTTPException) as exc:
        decode_token(token, _settings())
    assert exc.value.status_code == 401


def test_unsigned_token_is_rejected():
    def b64(value) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    token = b64({"alg": "none", "typ": "JWT"}) + "." + b64({"sub": "auth0|ada", "iss": ISSUER}) + "."
    with pytest.raises(HTTPException) as exc:
        decode_auth0_token(token, _settings())
    assert exc.value.status_code == 401


def test_production_rejects_non_auth0_tokens():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": "user", "aud": "authenticated", "exp": now + timedelta(minutes=5)},
        "test-secret",
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc:
        decode_token(token, _settings(app_env="production"))
    assert exc.value.status_code == 401


def test_unverified_email_is_refused():
    with pytest.raises(HTTPException) as exc:
        resolve_auth0_profile(
            {"sub": "auth0|ada", "email": "ada@example.com", "email_verified": False},
            "token",
            None,
            _settings(),
        )
    assert exc.value.status_code == 403


def test_local_auth0_user_is_provisioned_once():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    first = ensure_local_auth0_user(session, "auth0|ada", "Ada@Example.com", "Ada")
    second = ensure_local_auth0_user(session, "auth0|ada", "ada@example.com", "Ada")
    profile = session.get(Profile, first)
    accounts = session.scalars(select(Account).where(Account.org_id == profile.org_id)).all()
    assert first == second
    assert profile.email == "ada@example.com"
    assert len(accounts) == len(DEFAULT_ACCOUNTS)
    assert session.get(AuthIdentity, ("auth0", "auth0|ada")).user_id == first
    session.close()


def test_local_auth0_links_existing_email():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    first = ensure_local_auth0_user(session, "auth0|ada", "ada@example.com", "Ada")
    linked = ensure_local_auth0_user(session, "google-oauth2|ada", "ada@example.com", "Ada")
    assert linked == first
    session.close()


class _Query:
    def __init__(self, store, name):
        self.store = store
        self.name = name
        self.filters = []
        self.payload = None

    def select(self, *_args):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def limit(self, _count):
        return self

    def insert(self, payload):
        self.payload = payload
        return self

    def execute(self):
        rows = self.store.setdefault(self.name, [])
        if self.payload is not None:
            rows.append(dict(self.payload))
            return SimpleNamespace(data=[self.payload])
        matched = [row for row in rows if all(row.get(key) == value for key, value in self.filters)]
        return SimpleNamespace(data=matched)


class _Admin:
    def __init__(self):
        self.calls = 0

    def create_user(self, _attrs):
        self.calls += 1
        return SimpleNamespace(user=SimpleNamespace(id="11111111-1111-4111-8111-111111111111"))


class _Client:
    def __init__(self):
        self.store = {}
        self.admin = _Admin()
        self.auth = SimpleNamespace(admin=self.admin)

    def table(self, name):
        return _Query(self.store, name)


def test_supabase_auth0_link_is_created_once():
    client = _Client()
    first = supabase_user_for_auth0(client, "auth0|ada", "ada@example.com", "Ada")
    second = supabase_user_for_auth0(client, "auth0|ada", "ada@example.com", "Ada")
    assert first == second == "11111111-1111-4111-8111-111111111111"
    assert client.admin.calls == 1


def test_supabase_auth0_links_an_existing_profile():
    client = _Client()

    def duplicate(_attrs):
        raise RuntimeError("A user with this email address has already been registered")

    client.admin.create_user = duplicate
    client.store["profiles"] = [{"id": "22222222-2222-4222-8222-222222222222", "email": "ada@example.com"}]
    linked = supabase_user_for_auth0(client, "auth0|ada", "ada@example.com", "Ada")
    assert linked == "22222222-2222-4222-8222-222222222222"


def test_production_auth0_requires_audience():
    settings = _settings(app_env="production", supabase_url="https://example.supabase.co", auth0_audience="")
    with pytest.raises(RuntimeError, match="AUTH0_AUDIENCE"):
        assert_production(settings)


def test_production_without_auth0_still_starts():
    assert_production(
        _settings(
            app_env="production",
            supabase_url="https://example.supabase.co",
            auth0_domain="",
            auth0_audience="",
            auth0_client_id="",
        )
    )
