"""Deployment modes and the mimb_session contract (tenancy.py)."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from mastodon_is_my_blog import queries, tenancy
from mastodon_is_my_blog.store import MetaAccount

SIGNING_KEY = "test-signing-key-please-rotate-0123456789abcdef"


def make_session_token(
    *,
    tenant_id: object = 7,
    key: str = SIGNING_KEY,
    issuer: str = tenancy.SESSION_ISSUER,
    expires_in: timedelta = timedelta(hours=1),
    sub: str = "user-123",
) -> str:
    payload = {
        "sub": sub,
        "tenant_id": tenant_id,
        "email": "peep@example.com",
        "iss": issuer,
        "exp": datetime.now(timezone.utc) + expires_in,
    }
    return jwt.encode(payload, key, algorithm="HS256")


class StubRequest:
    def __init__(self, cookies: dict | None = None, headers: dict | None = None):
        self.cookies = cookies or {}
        self.headers = headers or {}


class TestGetMode:
    def test_defaults_to_local(self, monkeypatch):
        monkeypatch.delenv("MIMB_MODE", raising=False)
        assert tenancy.get_mode() == tenancy.MODE_LOCAL
        assert not tenancy.is_server_mode()

    def test_server_mode(self, monkeypatch):
        monkeypatch.setenv("MIMB_MODE", "server")
        assert tenancy.is_server_mode()

    def test_mode_is_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("MIMB_MODE", "  SERVER ")
        assert tenancy.is_server_mode()

    def test_unknown_mode_rejected(self, monkeypatch):
        monkeypatch.setenv("MIMB_MODE", "cloud")
        with pytest.raises(ValueError):
            tenancy.get_mode()


class TestCheckServerModeEnv:
    def test_reports_all_missing_vars(self, monkeypatch):
        for name in tenancy.SERVER_MODE_REQUIRED_ENV:
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(RuntimeError) as excinfo:
            tenancy.check_server_mode_env()
        for name in tenancy.SERVER_MODE_REQUIRED_ENV:
            assert name in str(excinfo.value)

    def test_passes_when_configured(self, monkeypatch):
        for name in tenancy.SERVER_MODE_REQUIRED_ENV:
            monkeypatch.setenv(name, "value")
        tenancy.check_server_mode_env()


class TestVerifySessionToken:
    def test_round_trip(self, monkeypatch):
        monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING_KEY)
        claims = tenancy.verify_session_token(make_session_token())
        assert claims.user_id == "user-123"
        assert claims.tenant_id == 7
        assert claims.email == "peep@example.com"

    def test_missing_signing_key(self, monkeypatch):
        monkeypatch.delenv("SESSION_SIGNING_KEY", raising=False)
        with pytest.raises(tenancy.SessionValidationError):
            tenancy.verify_session_token(make_session_token())

    def test_wrong_signature(self, monkeypatch):
        monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING_KEY)
        token = make_session_token(key="some-other-key")
        with pytest.raises(tenancy.SessionValidationError):
            tenancy.verify_session_token(token)

    def test_expired(self, monkeypatch):
        monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING_KEY)
        token = make_session_token(expires_in=timedelta(hours=-1))
        with pytest.raises(tenancy.SessionValidationError):
            tenancy.verify_session_token(token)

    def test_wrong_issuer(self, monkeypatch):
        monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING_KEY)
        token = make_session_token(issuer="somebody_else")
        with pytest.raises(tenancy.SessionValidationError):
            tenancy.verify_session_token(token)

    @pytest.mark.parametrize("tenant_id", [None, "7", 1.5, True])
    def test_tenant_id_must_be_int(self, monkeypatch, tenant_id):
        monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING_KEY)
        token = make_session_token(tenant_id=tenant_id)
        with pytest.raises(tenancy.SessionValidationError):
            tenancy.verify_session_token(token)


@pytest.mark.asyncio
class TestGetCurrentMetaAccountServerMode:
    @pytest.fixture(autouse=True)
    def server_mode(self, monkeypatch, patch_async_session):
        monkeypatch.setenv("MIMB_MODE", "server")
        monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING_KEY)
        patch_async_session(queries)

    async def test_no_cookie_is_401(self):
        with pytest.raises(HTTPException) as excinfo:
            await queries.get_current_meta_account(StubRequest())
        assert excinfo.value.status_code == 401

    async def test_bad_cookie_is_401(self):
        request = StubRequest(cookies={tenancy.SESSION_COOKIE_NAME: "garbage"})
        with pytest.raises(HTTPException) as excinfo:
            await queries.get_current_meta_account(request)
        assert excinfo.value.status_code == 401

    async def test_header_override_is_ignored_in_server_mode(self, db_session):
        db_session.add(MetaAccount(id=99, username="victim"))
        await db_session.commit()
        request = StubRequest(headers={"X-Meta-Account-ID": "99"})
        with pytest.raises(HTTPException) as excinfo:
            await queries.get_current_meta_account(request)
        assert excinfo.value.status_code == 401

    async def test_valid_session_lazily_provisions_tenant(self, db_session_factory):
        request = StubRequest(cookies={tenancy.SESSION_COOKIE_NAME: make_session_token(tenant_id=7)})
        meta = await queries.get_current_meta_account(request)
        assert meta.username == "tenant_7"

        # Second request resolves the same MetaAccount, no duplicate
        again = await queries.get_current_meta_account(request)
        assert again.id == meta.id

        async with db_session_factory() as session:
            rows = (await session.execute(select(MetaAccount))).scalars().all()
        assert [row.username for row in rows] == ["tenant_7"]

    async def test_disabled_tenant_is_403(self, db_session):
        # The control plane pushed enabled=False (suspension); a valid session
        # cookie must not get through.
        db_session.add(MetaAccount(id=7, username="tenant_7", enabled=False))
        await db_session.commit()
        request = StubRequest(cookies={tenancy.SESSION_COOKIE_NAME: make_session_token(tenant_id=7)})
        with pytest.raises(HTTPException) as excinfo:
            await queries.get_current_meta_account(request)
        assert excinfo.value.status_code == 403
        assert "suspended" in excinfo.value.detail.lower()

    async def test_tenants_resolve_to_distinct_accounts(self):
        request_a = StubRequest(cookies={tenancy.SESSION_COOKIE_NAME: make_session_token(tenant_id=1)})
        request_b = StubRequest(cookies={tenancy.SESSION_COOKIE_NAME: make_session_token(tenant_id=2)})
        meta_a = await queries.get_current_meta_account(request_a)
        meta_b = await queries.get_current_meta_account(request_b)
        assert meta_a.id != meta_b.id
        assert {meta_a.username, meta_b.username} == {"tenant_1", "tenant_2"}
