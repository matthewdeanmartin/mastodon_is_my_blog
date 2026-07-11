"""Neutral per-tenant limits on the product server (sprint 04).

The control plane pushes {enabled, max_identities, max_storage_bytes} via
PUT /internal/tenants/{id}/limits; this file covers the identity-connect gate
(routes/admin.py ensure_identity_capacity) and the schema backfill for
pre-limits databases (store.ensure_meta_accounts_schema).
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from mastodon_is_my_blog.routes import admin
from mastodon_is_my_blog.routes.admin import ensure_identity_capacity
from test.conftest import make_identity, make_meta_account


@pytest.fixture
def server_mode(monkeypatch, patch_async_session):
    from mastodon_is_my_blog.secret_columns import generate_key

    monkeypatch.setenv("MIMB_MODE", "server")
    # Server mode encrypts identity token columns at rest.
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    patch_async_session(admin)


@pytest.mark.asyncio
class TestEnsureIdentityCapacity:
    async def test_unlimited_when_no_limit_pushed(self, server_mode, db_session):
        meta = make_meta_account(username="tenant_1")
        db_session.add(meta)
        await db_session.commit()
        assert meta.max_identities is None
        await ensure_identity_capacity(meta, base_url="https://a.social")

    async def test_under_limit_allowed(self, server_mode, db_session):
        meta = make_meta_account(username="tenant_1")
        meta.max_identities = 2
        db_session.add(meta)
        db_session.add(make_identity(meta_account_id=1, api_base_url="https://a.social", acct="me@a.social"))
        await db_session.commit()
        await ensure_identity_capacity(meta, base_url="https://b.social")

    async def test_at_limit_rejected(self, server_mode, db_session):
        meta = make_meta_account(username="tenant_1")
        meta.max_identities = 1
        db_session.add(meta)
        db_session.add(make_identity(meta_account_id=1, api_base_url="https://a.social", acct="me@a.social"))
        await db_session.commit()
        with pytest.raises(HTTPException) as excinfo:
            await ensure_identity_capacity(meta, base_url="https://b.social")
        assert excinfo.value.status_code == 403
        assert "plan" in excinfo.value.detail.lower()

    async def test_reauth_of_existing_identity_allowed_at_limit(self, server_mode, db_session):
        meta = make_meta_account(username="tenant_1")
        meta.max_identities = 1
        db_session.add(meta)
        db_session.add(make_identity(meta_account_id=1, api_base_url="https://a.social", acct="me@a.social"))
        await db_session.commit()
        # OAuth start: acct unknown, same instance -> allowed
        await ensure_identity_capacity(meta, base_url="https://a.social")
        # Callback/persist: same instance + acct -> allowed
        await ensure_identity_capacity(meta, base_url="https://a.social", acct="me@a.social")
        # But a NEW acct on the same instance is a new identity -> rejected
        with pytest.raises(HTTPException):
            await ensure_identity_capacity(meta, base_url="https://a.social", acct="other@a.social")

    async def test_noop_in_local_mode(self, monkeypatch):
        monkeypatch.setenv("MIMB_MODE", "local")
        meta = make_meta_account(username="default")
        meta.max_identities = 0
        # Never queries the DB in local mode — limits are a hosted construct.
        await ensure_identity_capacity(meta, base_url="https://a.social")


@pytest.mark.asyncio
async def test_meta_accounts_schema_backfill(monkeypatch):
    """A DB created before sprint 04 lacks the limit columns; init_db's shim
    must add them (create_all never alters existing tables) with enabled
    defaulting to 1 so existing accounts keep working.
    """
    from mastodon_is_my_blog import store

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE meta_accounts (id INTEGER PRIMARY KEY, username VARCHAR UNIQUE, created_at DATETIME)"))
        await conn.execute(text("INSERT INTO meta_accounts (id, username) VALUES (1, 'default')"))
    monkeypatch.setattr(store, "engine", engine)

    await store.ensure_meta_accounts_schema()

    async with engine.begin() as conn:
        columns = {row[1] for row in await conn.execute(text("PRAGMA table_info(meta_accounts)"))}
        assert {"enabled", "max_identities", "max_storage_bytes"} <= columns
        enabled = (await conn.execute(text("SELECT enabled FROM meta_accounts WHERE id = 1"))).scalar_one()
        assert enabled == 1
    await engine.dispose()
