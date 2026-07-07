from test.conftest import make_identity, make_meta_account
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from mastodon_is_my_blog import main
from mastodon_is_my_blog.queries import get_current_meta_account
from mastodon_is_my_blog.routes import admin
from mastodon_is_my_blog.store import MetaAccount, OAuthPendingConnection


async def async_noop(*args, **kwargs) -> None:
    return None


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch, db_session_factory) -> TestClient:
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "get_or_create_default_meta_account", async_noop)
    monkeypatch.setattr(main, "sync_configured_identities", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)
    monkeypatch.setattr(admin, "async_session", db_session_factory)
    monkeypatch.setattr("mastodon_is_my_blog.store.async_session", db_session_factory)

    def override_meta_account():
        return SimpleNamespace(id=7, username="test-meta")

    main.app.dependency_overrides[get_current_meta_account] = override_meta_account

    with TestClient(main.app) as client:
        yield client

    main.app.dependency_overrides.clear()


class DummyClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def log_in(self, **kwargs) -> str:
        return "new-access-token"

    def account_verify_credentials(self) -> dict:
        return {"acct": "alice@example.com", "id": "42"}


def _stub_persist(monkeypatch: pytest.MonkeyPatch, module) -> None:
    """Bypasses real keyring/config-file writes; pre-seeded DB row supplies
    the identity that sync_configured_identities would otherwise create."""
    monkeypatch.setattr(module, "upsert_configured_account", lambda *a, **k: None)
    monkeypatch.setattr(module, "set_account_credentials", lambda *a, **k: None)
    monkeypatch.setattr(module, "list_account_summaries", lambda: [])
    monkeypatch.setattr(module, "sync_configured_identities", async_noop)


@pytest.mark.asyncio
async def test_persist_identity_creates_and_updates_identity(
    monkeypatch: pytest.MonkeyPatch, db_session_factory
) -> None:
    _stub_persist(monkeypatch, admin)

    async with db_session_factory() as session:
        session.add(make_meta_account(meta_id=7))
        session.add(
            make_identity(
                identity_id=1,
                meta_account_id=7,
                config_name="ALICE",
                acct="",
                account_id="",
            )
        )
        await session.commit()

    monkeypatch.setattr(admin, "build_unique_account_name", lambda preferred, existing: "ALICE")
    monkeypatch.setattr(admin, "async_session", db_session_factory)

    meta = MetaAccount(id=7, username="test-meta")
    result = await admin.persist_identity(
        meta,
        "https://example.social",
        "client-id",
        "client-secret",
        "new-access-token",
        {"acct": "alice@example.com", "id": "42"},
    )

    assert result == {"status": "created", "acct": "alice@example.com"}

    from sqlalchemy import select

    from mastodon_is_my_blog.store import MastodonIdentity

    async with db_session_factory() as session:
        stmt = select(MastodonIdentity).where(MastodonIdentity.config_name == "ALICE")
        identity = (await session.execute(stmt)).scalar_one()
        assert identity.acct == "alice@example.com"
        assert identity.account_id == "42"


@pytest.mark.asyncio
async def test_add_identity_api_key_creates_identity(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch, db_session_factory
) -> None:
    _stub_persist(monkeypatch, admin)
    monkeypatch.setattr(
        admin, "build_unique_account_name", lambda preferred, existing: "ALICE"
    )
    monkeypatch.setattr(admin, "client", lambda **kwargs: DummyClient(**kwargs))

    async with db_session_factory() as session:
        session.add(make_meta_account(meta_id=7))
        session.add(
            make_identity(
                identity_id=1,
                meta_account_id=7,
                config_name="ALICE",
                acct="",
                account_id="",
            )
        )
        await session.commit()

    response = api_client.post(
        "/api/admin/identities/api-key",
        json={
            "base_url": "https://example.social",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "access_token": "new-access-token",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "created", "acct": "alice@example.com"}


@pytest.mark.asyncio
async def test_auth_callback_consumes_pending_connection_and_persists_identity(
    monkeypatch: pytest.MonkeyPatch, db_session_factory
) -> None:
    monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
    _stub_persist(monkeypatch, admin)
    monkeypatch.setattr(
        admin, "build_unique_account_name", lambda preferred, existing: "ALICE"
    )
    monkeypatch.setattr(main, "client", lambda **kwargs: DummyClient(**kwargs))
    monkeypatch.setattr(main, "sync_accounts_friends_followers", async_noop)
    monkeypatch.setattr(main, "sync_user_timeline", async_noop)
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "sync_configured_identities", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)

    async def fake_get_or_create_default_meta_account():
        return MetaAccount(id=7, username="test-meta")

    monkeypatch.setattr(
        main, "get_or_create_default_meta_account", fake_get_or_create_default_meta_account
    )

    async with db_session_factory() as session:
        session.add(make_meta_account(meta_id=7))
        session.add(
            make_identity(
                identity_id=1,
                meta_account_id=7,
                config_name="ALICE",
                acct="",
                account_id="",
            )
        )
        session.add(
            OAuthPendingConnection(
                state="abc123",
                meta_account_id=7,
                base_url="https://example.social",
                client_id="client-id",
                client_secret="client-secret",
            )
        )
        await session.commit()

    monkeypatch.setattr("mastodon_is_my_blog.store.async_session", db_session_factory)
    monkeypatch.setattr(admin, "async_session", db_session_factory)

    from fastapi.testclient import TestClient

    with TestClient(main.app) as client:
        response = client.get(
            "/auth/callback?code=somecode&state=abc123", follow_redirects=False
        )

    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost:4200/#/admin"

    from sqlalchemy import select

    from mastodon_is_my_blog.store import MastodonIdentity

    async with db_session_factory() as session:
        stmt = select(MastodonIdentity).where(MastodonIdentity.config_name == "ALICE")
        identity = (await session.execute(stmt)).scalar_one()
        assert identity.acct == "alice@example.com"

        pending = (
            await session.execute(select(OAuthPendingConnection))
        ).scalar_one_or_none()
        assert pending is None


def test_auth_callback_server_mode_spawns_first_sync(
    monkeypatch: pytest.MonkeyPatch, db_session_factory
) -> None:
    """Server mode must kick a tenant-scoped background sync after connect —
    otherwise every page is an empty state until the next scheduled sync
    (sprint-05 testing feedback)."""
    from mastodon_is_my_blog.routes import internal

    from mastodon_is_my_blog.secret_columns import generate_key

    monkeypatch.setenv("MIMB_MODE", "server")
    # Server-mode writes encrypt credential columns (incl. the pending row).
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
    monkeypatch.setenv("SESSION_SIGNING_KEY", "test-signing-key-0123456789abcdef")
    monkeypatch.setenv("HANDOFF_SHARED_SECRET", "test-handoff-secret")
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    monkeypatch.setattr(main, "client", lambda **kwargs: DummyClient(**kwargs))
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "get_or_create_default_meta_account", async_noop)
    monkeypatch.setattr(main, "sync_configured_identities", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)
    monkeypatch.setattr(admin, "async_session", db_session_factory)
    monkeypatch.setattr("mastodon_is_my_blog.store.async_session", db_session_factory)

    tenant_meta = MetaAccount(id=9, username="tenant_9")

    async def fake_get_meta(meta_id: int) -> MetaAccount:
        assert meta_id == 9
        return tenant_meta

    monkeypatch.setattr(main, "get_meta_account_by_id", fake_get_meta)

    spawned: list[str] = []

    def fake_spawn(coro, *, label: str) -> None:
        spawned.append(label)
        coro.close()

    monkeypatch.setattr(internal, "spawn_background", fake_spawn)

    import asyncio

    async def seed() -> None:
        async with db_session_factory() as session:
            session.add(
                OAuthPendingConnection(
                    state="srv123",
                    meta_account_id=9,
                    base_url="https://example.social",
                    client_id="client-id",
                    client_secret="client-secret",
                )
            )
            await session.commit()

    asyncio.run(seed())

    with TestClient(main.app) as client:
        response = client.get(
            "/auth/callback?code=somecode&state=srv123", follow_redirects=False
        )

    assert response.status_code == 307
    assert response.headers["location"] == "https://app.example.com/#/admin"
    assert spawned == ["first-sync-tenant_9"]


def test_auth_callback_rejects_unknown_state(
    monkeypatch: pytest.MonkeyPatch, db_session_factory
) -> None:
    monkeypatch.setattr("mastodon_is_my_blog.store.async_session", db_session_factory)
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "get_or_create_default_meta_account", async_noop)
    monkeypatch.setattr(main, "sync_configured_identities", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)

    with TestClient(main.app) as client:
        response = client.get("/auth/callback?code=somecode&state=unknown")

    assert response.status_code == 400
