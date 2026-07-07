"""GET /api/whoami — the "whose blog is whose" surface (remaining_work §3.1).

Server mode must echo the session's identity claims; local mode must say so
without demanding a session. Uses TestClient like test_oauth_connect.py,
with the same lifespan stubs.
"""

import pytest
from fastapi.testclient import TestClient

from mastodon_is_my_blog import main, tenancy
from test.test_tenancy import SIGNING_KEY, make_session_token


async def async_noop(*args, **kwargs) -> None:
    return None


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "get_or_create_default_meta_account", async_noop)
    monkeypatch.setattr(main, "sync_configured_identities", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)
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

    api_client.cookies.set(
        tenancy.SESSION_COOKIE_NAME, make_session_token(tenant_id=7)
    )
    response = api_client.get("/api/whoami")
    assert response.status_code == 200
    assert response.json() == {
        "mode": "server",
        "email": "peep@example.com",
        "tenant_id": 7,
        "account_url": "https://account.example.com",
    }


def test_server_mode_requires_a_session(api_client, monkeypatch):
    monkeypatch.setenv("MIMB_MODE", "server")
    monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING_KEY)

    response = api_client.get("/api/whoami")
    assert response.status_code == 401

    api_client.cookies.set(tenancy.SESSION_COOKIE_NAME, "garbage")
    response = api_client.get("/api/whoami")
    assert response.status_code == 401
