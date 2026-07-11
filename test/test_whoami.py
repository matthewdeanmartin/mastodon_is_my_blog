"""GET /api/whoami — the "whose blog is whose" surface (remaining_work §3.1).

Server mode must echo the session's identity claims; local mode must say so
without demanding a session. Uses TestClient like test_oauth_connect.py,
with the same lifespan stubs.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from mastodon_is_my_blog import main, tenancy
from test.test_tenancy import SIGNING_KEY, make_session_token


async def async_noop(*args, **kwargs) -> None:
    return None


async def fake_enabled_meta(request) -> SimpleNamespace:
    return SimpleNamespace(id=7, username="tenant_7", enabled=True)


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "get_or_create_default_meta_account", async_noop)
    monkeypatch.setattr(main, "sync_configured_identities", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)
    # whoami consults the same tenant gate as the data routes; stub it so
    # these tests never touch the real DB (the gate itself is covered by
    # test_tenancy.test_disabled_tenant_is_403).
    monkeypatch.setattr(main, "get_current_meta_account", fake_enabled_meta)
    with TestClient(main.app) as client:
        yield client


def test_local_mode_is_open_and_anonymous(api_client, monkeypatch):
    monkeypatch.delenv("MIMB_MODE", raising=False)
    response = api_client.get("/api/whoami")
    assert response.status_code == 200
    assert response.json() == {
        "mode": "local",
        "email": None,
        "tenant_id": None,
        "account_url": None,
    }


def test_server_mode_echoes_session_claims(api_client, monkeypatch):
    monkeypatch.setenv("MIMB_MODE", "server")
    monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING_KEY)
    monkeypatch.setenv("ACCOUNT_PORTAL_URL", "https://account.example.com/")

    api_client.cookies.set(tenancy.SESSION_COOKIE_NAME, make_session_token(tenant_id=7))
    response = api_client.get("/api/whoami")
    assert response.status_code == 200
    assert response.json() == {
        "mode": "server",
        "email": "peep@example.com",
        "tenant_id": 7,
        "account_url": "https://account.example.com",
    }


def test_server_mode_403s_when_tenant_disabled(api_client, monkeypatch):
    """whoami must run the same enabled gate as the data routes, or a
    suspended tenant's UI keeps saying "signed in" while everything else 403s.
    """
    monkeypatch.setenv("MIMB_MODE", "server")
    monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING_KEY)

    async def gate_rejects(request):
        raise HTTPException(403, "This account is suspended.")

    monkeypatch.setattr(main, "get_current_meta_account", gate_rejects)
    api_client.cookies.set(tenancy.SESSION_COOKIE_NAME, make_session_token(tenant_id=7))
    response = api_client.get("/api/whoami")
    assert response.status_code == 403


def test_server_mode_requires_a_session(api_client, monkeypatch):
    monkeypatch.setenv("MIMB_MODE", "server")
    monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING_KEY)

    response = api_client.get("/api/whoami")
    assert response.status_code == 401

    api_client.cookies.set(tenancy.SESSION_COOKIE_NAME, "garbage")
    response = api_client.get("/api/whoami")
    assert response.status_code == 401
