from datetime import timedelta
from test.conftest import make_identity, make_meta_account
from unittest.mock import patch

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from mastodon_is_my_blog import store
from mastodon_is_my_blog.datetime_helpers import utc_now
from mastodon_is_my_blog.utils.settings_loader import IdentityConfig


@pytest.mark.asyncio
async def test_init_db_creates_tables() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    try:
        with patch.object(store, "engine", engine):
            await store.init_db()

        async with engine.connect() as conn:
            table_names = set(
                (
                    await conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table'")
                    )
                )
                .scalars()
                .all()
            )

        assert {
            "meta_accounts",
            "mastodon_identities",
            "seen_posts",
            "tokens",
        }.issubset(table_names)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_or_create_default_meta_account_creates_and_reuses(
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(store)

    created = await store.get_or_create_default_meta_account()
    reused = await store.get_or_create_default_meta_account()

    async with db_session_factory() as session:
        count = (
            await session.execute(select(func.count()).select_from(store.MetaAccount))
        ).scalar_one()

    assert created.username == "default"
    assert reused.id == created.id
    assert count == 1


@pytest.mark.asyncio
async def test_sync_configured_identities_returns_early_without_identities(
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(store)

    with patch.object(store, "load_configured_identities", return_value={}):
        await store.sync_configured_identities()

    async with db_session_factory() as session:
        identity_count = (
            await session.execute(
                select(func.count()).select_from(store.MastodonIdentity)
            )
        ).scalar_one()

    assert identity_count == 0


@pytest.mark.asyncio
async def test_sync_configured_identities_creates_default_meta_and_new_identities(
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(store)
    configured_identities = {
        "MAIN": IdentityConfig(
            name="MAIN",
            base_url="https://mastodon.social",
            client_id="main-client",
            client_secret="main-secret",
            access_token="main-token",
        ),
        "ART": IdentityConfig(
            name="ART",
            base_url="https://art.example",
            client_id="art-client",
            client_secret="art-secret",
            access_token=None,
        ),
    }

    with patch.object(
        store,
        "load_configured_identities",
        return_value=configured_identities,
    ):
        await store.sync_configured_identities()

    async with db_session_factory() as session:
        meta = (
            await session.execute(
                select(store.MetaAccount).where(store.MetaAccount.username == "default")
            )
        ).scalar_one()
        identities = (
            (
                await session.execute(
                    select(store.MastodonIdentity).order_by(
                        store.MastodonIdentity.client_id
                    )
                )
            )
            .scalars()
            .all()
        )

    assert meta.username == "default"
    assert [identity.client_id for identity in identities] == [
        "art-client",
        "main-client",
    ]
    assert identities[0].acct == "art@unknown"
    assert identities[0].config_name == "ART"
    assert identities[0].access_token == ""
    assert identities[1].acct == "main@unknown"
    assert identities[1].config_name == "MAIN"
    assert identities[1].access_token == ""


@pytest.mark.asyncio
async def test_sync_configured_identities_updates_existing_identity(
    db_session,
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(store)
    db_session.add(make_meta_account())
    db_session.add(
        make_identity(
            api_base_url="https://mastodon.social",
            client_id="main-client",
            client_secret="old-secret",
            access_token="old-token",
            acct="main@unknown",
            account_id="0",
            config_name="OLD",
        )
    )
    await db_session.commit()

    configured_identities = {
        "MAIN": IdentityConfig(
            name="MAIN",
            base_url="https://mastodon.social",
            client_id="main-client",
            client_secret="new-secret",
            access_token="new-token",
        )
    }

    with patch.object(
        store,
        "load_configured_identities",
        return_value=configured_identities,
    ):
        await store.sync_configured_identities()

    async with db_session_factory() as session:
        identity = (await session.execute(select(store.MastodonIdentity))).scalar_one()

    assert identity.config_name == "MAIN"
    assert identity.client_secret == ""
    assert identity.access_token == ""


@pytest.mark.asyncio
async def test_get_default_identity_returns_none_without_default_meta(
    patch_async_session,
) -> None:
    patch_async_session(store)

    assert await store.get_default_identity() is None


@pytest.mark.asyncio
async def test_get_default_identity_returns_first_default_identity(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(store)
    db_session.add(make_meta_account())
    db_session.add_all(
        [
            make_identity(identity_id=1, acct="first@example.social"),
            make_identity(identity_id=2, acct="second@example.social"),
        ]
    )
    await db_session.commit()

    identity = await store.get_default_identity()

    assert identity is not None
    assert identity.id == 1


@pytest.mark.asyncio
async def test_update_last_sync_inserts_and_updates_state(
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(store)

    assert await store.get_last_sync("timeline:1:1") is None

    before = utc_now()
    await store.update_last_sync("timeline:1:1")
    first_value = await store.get_last_sync("timeline:1:1")
    await store.update_last_sync("timeline:1:1")
    second_value = await store.get_last_sync("timeline:1:1")

    async with db_session_factory() as session:
        state_count = (
            await session.execute(select(func.count()).select_from(store.AppState))
        ).scalar_one()

    assert first_value is not None
    assert second_value is not None
    assert first_value >= before
    assert second_value >= first_value
    assert state_count == 1


@pytest.mark.asyncio
async def test_get_token_prefers_database_value_and_falls_back_to_env(
    db_session,
    patch_async_session,
    monkeypatch,
) -> None:
    patch_async_session(store)
    monkeypatch.setenv("MASTODON_ACCESS_TOKEN", "env-token")

    assert await store.get_token() == "env-token"

    db_session.add(store.Token(key="mastodon_access_token", value="db-token"))
    await db_session.commit()

    assert await store.get_token() == "db-token"


@pytest.mark.asyncio
async def test_get_token_prefers_configured_identity_token(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(store)
    db_session.add(make_meta_account())
    db_session.add(make_identity(config_name="MAIN", access_token=""))
    await db_session.commit()

    with patch.object(
        store,
        "resolve_identity_config",
        return_value=IdentityConfig(
            name="MAIN",
            base_url="https://example.social",
            client_id="client-id",
            client_secret="client-secret",
            access_token="keyring-token",
        ),
    ):
        assert await store.get_token() == "keyring-token"


@pytest.mark.asyncio
async def test_set_token_updates_default_identity_when_present(
    db_session,
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(store)
    db_session.add(make_meta_account())
    db_session.add(make_identity(access_token="old-token"))
    await db_session.commit()

    await store.set_token("new-token")

    async with db_session_factory() as session:
        identity = (await session.execute(select(store.MastodonIdentity))).scalar_one()
        token_count = (
            await session.execute(select(func.count()).select_from(store.Token))
        ).scalar_one()

    assert identity.access_token == "new-token"
    assert token_count == 0


@pytest.mark.asyncio
async def test_set_token_writes_keyring_for_configured_identity(
    db_session,
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(store)
    db_session.add(make_meta_account())
    db_session.add(make_identity(config_name="MAIN", access_token="old-token"))
    await db_session.commit()

    with patch.object(store, "set_credential") as set_credential_mock:
        await store.set_token("new-token")

    async with db_session_factory() as session:
        identity = (await session.execute(select(store.MastodonIdentity))).scalar_one()

    set_credential_mock.assert_called_once_with("MAIN", "access_token", "new-token")
    assert identity.access_token == ""


@pytest.mark.asyncio
async def test_set_token_uses_legacy_token_table_without_default_identity(
    db_session,
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(store)

    await store.set_token("first-token")
    await store.set_token("second-token")

    async with db_session_factory() as session:
        tokens = (await session.execute(select(store.Token))).scalars().all()

    assert len(tokens) == 1
    assert tokens[0].value == "second-token"


@pytest.mark.asyncio
async def test_mark_post_seen_mark_posts_seen_and_seen_queries(
    db_session,
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(store)
    now = utc_now()
    old_time = now - timedelta(days=2)
    recent_time = now - timedelta(hours=1)
    db_session.add_all(
        [
            store.SeenPost(meta_account_id=1, post_id="old-post", seen_at=old_time),
            store.SeenPost(
                meta_account_id=1, post_id="recent-post", seen_at=recent_time
            ),
        ]
    )
    await db_session.commit()

    await store.mark_post_seen(1, "recent-post")
    await store.mark_post_seen(1, "new-post")
    await store.mark_posts_seen(1, [])
    await store.mark_posts_seen(1, ["bulk-1", "bulk-1", "bulk-2"])

    async with db_session_factory() as session:
        posts = (
            (
                await session.execute(
                    select(store.SeenPost).where(store.SeenPost.meta_account_id == 1)
                )
            )
            .scalars()
            .all()
        )

    assert sorted(post.post_id for post in posts) == [
        "bulk-1",
        "bulk-2",
        "new-post",
        "old-post",
        "recent-post",
    ]
    assert await store.get_seen_posts(1, []) == set()
    assert await store.get_seen_posts(1, ["missing", "recent-post", "bulk-2"]) == {
        "recent-post",
        "bulk-2",
    }
    assert await store.get_unread_count(1) == 5
    assert await store.get_unread_count(1, since=now - timedelta(hours=2)) == 4
