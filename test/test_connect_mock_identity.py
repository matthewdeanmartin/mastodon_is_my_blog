"""POST /internal/tenants/{id}/connect-mock-identity (sprint 05 demo wiring).

Headless identity connect against mastodon_mock's permissive code flow
(`mockcode_{username}`), then sync + blog build — synchronous so seed-demo
gets a working demo blog in one job. Localhost-only by design.
"""

from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from mastodon_is_my_blog import tenant_export
from mastodon_is_my_blog.routes import admin, internal

SECRET = "test-handoff-secret"
AUTH = {"Authorization": f"Bearer {SECRET}"}


@pytest_asyncio.fixture
async def client(monkeypatch, patch_async_session, tmp_path):
    from mastodon_is_my_blog.secret_columns import generate_key

    monkeypatch.setenv("HANDOFF_SHARED_SECRET", SECRET)
    monkeypatch.setenv("MIMB_MODE", "server")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("ELEVENTY_SITE_DIR", str(tmp_path / "no-eleventy"))
    monkeypatch.setenv("BLOG_DIR", str(tmp_path / "blogs"))
    patch_async_session(tenant_export, admin)
    monkeypatch.setattr(internal, "sync_all_identities", AsyncMock(return_value=[]))

    from mastodon_is_my_blog import blog_build, storm_export

    patch_async_session(storm_export)
    app = FastAPI()
    app.include_router(internal.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://internal.test") as http:
        yield http
    del blog_build  # imported for patch_async_session side effects only


def mock_mastodon_mock(monkeypatch):
    """Route the endpoint's outbound httpx client at a fake mastodon_mock."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/apps":
            return httpx.Response(200, json={"client_id": "cid", "client_secret": "csecret"})
        if request.url.path == "/oauth/token":
            body = request.content.decode()
            if "mockcode_ada" not in body:
                return httpx.Response(400, json={"detail": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "tok"})
        if request.url.path == "/api/v1/accounts/verify_credentials":
            assert request.headers["Authorization"] == "Bearer tok"
            return httpx.Response(200, json={"acct": "ada", "id": "1"})
        return httpx.Response(404)

    real_async_client = httpx.AsyncClient

    def fake_async_client(**kwargs):
        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", fake_async_client)


@pytest.mark.asyncio
async def test_connects_syncs_and_builds(client, monkeypatch, tmp_path):
    mock_mastodon_mock(monkeypatch)
    response = await client.post(
        "/internal/tenants/3/connect-mock-identity",
        json={"job_id": 1, "base_url": "http://localhost:3000", "username": "ada"},
        headers=AUTH,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["acct"] == "ada"
    assert body["synced"] is True
    assert body["builder"] == "fallback"  # no Eleventy in tests

    # The identity really landed on the tenant's MetaAccount.
    meta = await tenant_export.get_tenant_meta_account("tenant_3")
    ids = await tenant_export.tenant_identity_ids(meta.id)
    assert len(ids) == 1
    internal.sync_all_identities.assert_awaited_once()
    assert (tmp_path / "blogs" / "tenant_3" / "index.html").exists()


@pytest.mark.asyncio
async def test_refuses_non_localhost_targets(client):
    response = await client.post(
        "/internal/tenants/3/connect-mock-identity",
        json={"job_id": 1, "base_url": "https://mastodon.social", "username": "ada"},
        headers=AUTH,
    )
    assert response.status_code == 400
    assert "local mastodon_mock" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_mock_user_is_clean_502(client, monkeypatch):
    mock_mastodon_mock(monkeypatch)
    response = await client.post(
        "/internal/tenants/3/connect-mock-identity",
        json={"job_id": 1, "base_url": "http://localhost:3000", "username": "nobody"},
        headers=AUTH,
    )
    assert response.status_code == 502
    assert "nobody" in response.json()["detail"]
