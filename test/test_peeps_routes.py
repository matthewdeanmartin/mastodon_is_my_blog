from datetime import datetime
from test.conftest import (
    make_cached_account,
    make_cached_notification,
    make_cached_post,
    make_identity,
    make_meta_account,
)

import pytest
from fastapi.testclient import TestClient

from mastodon_is_my_blog import main
from mastodon_is_my_blog.queries import get_current_meta_account
from mastodon_is_my_blog.routes import peeps
from mastodon_is_my_blog.store import (
    CachedMyFavourite,
)


async def async_noop(*args, **kwargs) -> None:
    return None


def make_my_favourite(
    status_id: str = "fav-1",
    *,
    meta_account_id: int = 1,
    identity_id: int = 1,
    target_account_id: str = "account-2",
    target_acct: str = "them@example.social",
    favourited_at: datetime | None = None,
) -> CachedMyFavourite:
    return CachedMyFavourite(
        status_id=status_id,
        meta_account_id=meta_account_id,
        identity_id=identity_id,
        target_account_id=target_account_id,
        target_acct=target_acct,
        favourited_at=favourited_at or datetime(2024, 3, 1),
    )


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch, db_session_factory) -> TestClient:
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "get_or_create_default_meta_account", async_noop)
    monkeypatch.setattr(main, "sync_configured_identities", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)
    monkeypatch.setattr(peeps, "async_session", db_session_factory)

    meta = make_meta_account(1)
    identity = make_identity(1, meta_account_id=1)

    async def fake_meta(request=None):
        return meta

    monkeypatch.setattr(main.app.dependency_overrides, "__setitem__", lambda k, v: None)
    main.app.dependency_overrides[get_current_meta_account] = fake_meta

    with TestClient(main.app, raise_server_exceptions=True) as client:
        yield client

    main.app.dependency_overrides.clear()


@pytest.fixture
def seeded_db(db_session_factory):
    """Returns a db_session_factory pre-seeded with typical peeps fixture data."""
    return db_session_factory


# --- Matrix tests ---


@pytest.mark.asyncio
async def test_matrix_returns_four_quadrants(
    monkeypatch: pytest.MonkeyPatch, db_session_factory
):
    """Matrix endpoint returns all four quadrant keys."""
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "get_or_create_default_meta_account", async_noop)
    monkeypatch.setattr(main, "sync_configured_identities", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)
    monkeypatch.setattr(peeps, "async_session", db_session_factory)

    meta = make_meta_account(1)
    identity = make_identity(1, meta_account_id=1)

    async with db_session_factory() as session:
        session.add(meta)
        session.add(identity)
        # Create fan: high inbound score
        session.add(
            make_cached_account(
                "account-fan",
                meta_account_id=1,
                identity_id=1,
                acct="fan@example.social",
                is_following=False,
            )
        )
        for i in range(5):
            session.add(
                make_cached_notification(
                    f"notif-fan-{i}",
                    meta_account_id=1,
                    identity_id=1,
                    notification_type="mention",
                    account_id="account-fan",
                    account_acct="fan@example.social",
                    created_at=datetime(2024, 3, 1),
                )
            )
        await session.commit()

    async def fake_meta(request=None):
        return meta

    main.app.dependency_overrides[get_current_meta_account] = fake_meta

    with TestClient(main.app, raise_server_exceptions=False) as client:
        resp = client.get("/api/peeps/matrix?identity_id=1")

    main.app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert "inner_circle" in data
    assert "fans" in data
    assert "idols" in data
    assert "broadcasters" in data


@pytest.mark.asyncio
async def test_matrix_empty_returns_empty_quadrants(
    monkeypatch: pytest.MonkeyPatch, db_session_factory
):
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "get_or_create_default_meta_account", async_noop)
    monkeypatch.setattr(main, "sync_configured_identities", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)
    monkeypatch.setattr(peeps, "async_session", db_session_factory)

    meta = make_meta_account(1)
    identity = make_identity(1, meta_account_id=1)

    async with db_session_factory() as session:
        session.add(meta)
        session.add(identity)
        await session.commit()

    async def fake_meta(request=None):
        return meta

    main.app.dependency_overrides[get_current_meta_account] = fake_meta

    with TestClient(main.app, raise_server_exceptions=False) as client:
        resp = client.get("/api/peeps/matrix?identity_id=1")

    main.app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["inner_circle"] == []
    assert data["fans"] == []
    assert data["idols"] == []
    assert data["broadcasters"] == []


# --- Dossier tests ---


@pytest.mark.asyncio
async def test_dossier_returns_full_payload(
    monkeypatch: pytest.MonkeyPatch, db_session_factory
):
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "get_or_create_default_meta_account", async_noop)
    monkeypatch.setattr(main, "sync_configured_identities", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)
    monkeypatch.setattr(peeps, "async_session", db_session_factory)

    meta = make_meta_account(1)
    identity = make_identity(1, meta_account_id=1)

    async with db_session_factory() as session:
        session.add(meta)
        session.add(identity)
        session.add(
            make_cached_account(
                "account-1",
                meta_account_id=1,
                identity_id=1,
                acct="friend@example.social",
            )
        )
        await session.commit()

    async def fake_meta(request=None):
        return meta

    main.app.dependency_overrides[get_current_meta_account] = fake_meta

    with TestClient(main.app, raise_server_exceptions=False) as client:
        resp = client.get("/api/peeps/dossier/friend@example.social?identity_id=1")

    main.app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["acct"] == "friend@example.social"
    assert "interaction_history" in data
    assert "top_hashtags" in data
    assert "media_profile" in data
    assert "is_stale" in data


@pytest.mark.asyncio
async def test_dossier_404_for_unknown_account(
    monkeypatch: pytest.MonkeyPatch, db_session_factory
):
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "get_or_create_default_meta_account", async_noop)
    monkeypatch.setattr(main, "sync_configured_identities", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)
    monkeypatch.setattr(peeps, "async_session", db_session_factory)

    meta = make_meta_account(1)
    identity = make_identity(1, meta_account_id=1)

    async with db_session_factory() as session:
        session.add(meta)
        session.add(identity)
        await session.commit()

    async def fake_meta(request=None):
        return meta

    main.app.dependency_overrides[get_current_meta_account] = fake_meta

    with TestClient(main.app, raise_server_exceptions=False) as client:
        resp = client.get("/api/peeps/dossier/nobody@nowhere.example?identity_id=1")

    main.app.dependency_overrides.clear()

    assert resp.status_code == 404


# --- Follow/Unfollow tests ---


@pytest.mark.asyncio
async def test_follow_calls_mastodon_api(
    monkeypatch: pytest.MonkeyPatch, db_session_factory
):
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "get_or_create_default_meta_account", async_noop)
    monkeypatch.setattr(main, "sync_configured_identities", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)
    monkeypatch.setattr(peeps, "async_session", db_session_factory)

    meta = make_meta_account(1)
    identity = make_identity(1, meta_account_id=1)

    async with db_session_factory() as session:
        session.add(meta)
        session.add(identity)
        await session.commit()

    async def fake_meta(request=None):
        return meta

    from mastodon_is_my_blog.routes import peeps as peeps_module

    async def fake_follow(meta_id, identity, acct):
        return {"followed": True, "acct": acct}

    monkeypatch.setattr(peeps_module, "follow_account", fake_follow)

    main.app.dependency_overrides[get_current_meta_account] = fake_meta

    with TestClient(main.app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/peeps/dossier/friend@example.social/follow?identity_id=1"
        )

    main.app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["followed"] is True


# --- Timezone regression tests ---
#
# Both /matrix and /dossier used to compute ``datetime.now(UTC) - <db value>``.
# DB values are naive UTC, so that raised
# ``TypeError: can't subtract offset-naive and offset-aware datetimes``
# and the page would 500. These tests fail without the utc_now() / to_naive_utc()
# fix in routes/peeps.py. See mastodon_is_my_blog/datetime_helpers.py.


@pytest.mark.asyncio
async def test_dossier_does_not_blow_up_on_naive_db_post(
    monkeypatch: pytest.MonkeyPatch, db_session_factory
):
    """Repro: dossier with a CachedPost whose created_at is naive UTC.

    Pre-fix this 500'd because the staleness check did
    ``datetime.now(UTC) - latest_post_at``.
    """
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "get_or_create_default_meta_account", async_noop)
    monkeypatch.setattr(main, "sync_configured_identities", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)
    monkeypatch.setattr(peeps, "async_session", db_session_factory)

    meta = make_meta_account(1)
    identity = make_identity(1, meta_account_id=1)

    async with db_session_factory() as session:
        session.add(meta)
        session.add(identity)
        session.add(
            make_cached_account(
                "account-1",
                meta_account_id=1,
                identity_id=1,
                acct="friend@example.social",
            )
        )
        # Naive UTC, like rows produced by the live app
        session.add(
            make_cached_post(
                "post-1",
                meta_account_id=1,
                identity_id=1,
                author_acct="friend@example.social",
                author_id="account-1",
            )
        )
        await session.commit()

    async def fake_meta(request=None):
        return meta

    main.app.dependency_overrides[get_current_meta_account] = fake_meta

    # raise_server_exceptions=True so a 500 surfaces as a real exception
    with TestClient(main.app, raise_server_exceptions=True) as client:
        resp = client.get("/api/peeps/dossier/friend@example.social?identity_id=1")

    main.app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    # Post is from 2024-01-01 in conftest, so by any reasonable test-run date
    # it should be considered stale (>7 days old).
    assert data["is_stale"] is True


@pytest.mark.asyncio
async def test_matrix_does_not_blow_up_when_age_days_is_called(
    monkeypatch: pytest.MonkeyPatch, db_session_factory
):
    """Repro: /matrix calls ``_age_days(notification.created_at, now)``.

    Pre-fix this raised TypeError on the first naive notification because
    ``now`` was aware (datetime.now(UTC)).
    """
    from datetime import timedelta

    from mastodon_is_my_blog.datetime_helpers import utc_now

    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "get_or_create_default_meta_account", async_noop)
    monkeypatch.setattr(main, "sync_configured_identities", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)
    monkeypatch.setattr(peeps, "async_session", db_session_factory)

    meta = make_meta_account(1)
    identity = make_identity(1, meta_account_id=1)

    # Use a recent date so it falls inside the default 180-day window — that
    # was the gap that hid this bug: old notifications were filtered out by
    # the SQL ``created_at >= cutoff`` clause and never reached _age_days.
    recent = utc_now() - timedelta(days=5)

    async with db_session_factory() as session:
        session.add(meta)
        session.add(identity)
        session.add(
            make_cached_account(
                "account-fan",
                meta_account_id=1,
                identity_id=1,
                acct="fan@example.social",
                is_following=False,
            )
        )
        session.add(
            make_cached_notification(
                "notif-fan-1",
                meta_account_id=1,
                identity_id=1,
                notification_type="mention",
                account_id="account-fan",
                account_acct="fan@example.social",
                created_at=recent,
            )
        )
        await session.commit()

    async def fake_meta(request=None):
        return meta

    main.app.dependency_overrides[get_current_meta_account] = fake_meta

    with TestClient(main.app, raise_server_exceptions=True) as client:
        resp = client.get("/api/peeps/matrix?identity_id=1")

    main.app.dependency_overrides.clear()

    assert resp.status_code == 200
