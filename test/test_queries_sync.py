from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from mastodon_is_my_blog import queries, store
from test.conftest import (
    make_account_data,
    make_cached_post,
    make_identity,
    make_meta_account,
    make_status,
)


@pytest.mark.asyncio
async def test_bulk_upsert_helpers_handle_empty_inputs(db_session) -> None:
    await queries.bulk_upsert_accounts(db_session, 1, 1, [])
    assert await queries.bulk_upsert_posts(db_session, 1, 1, []) == (0, 0)


@pytest.mark.asyncio
async def test_get_counts_optimized_filters_by_user(db_session) -> None:
    db_session.add_all(
        [
            make_cached_post(
                post_id="alice-short",
                author_acct="alice@example.social",
                content="short alice post",
            ),
            make_cached_post(
                post_id="bob-short",
                author_acct="bob@example.social",
                content="short bob post",
            ),
        ]
    )
    await db_session.commit()

    stats = await queries.get_counts_optimized(
        db_session, 1, 1, user="alice@example.social"
    )

    assert stats["user"] == "alice@example.social"
    assert stats["everyone"] == {"total": 1, "unseen": 1}
    assert stats["shorts"] == {"total": 1, "unseen": 1}


@pytest.mark.asyncio
async def test_sync_all_identities_aggregates_each_identity_result(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(queries)
    meta = make_meta_account(meta_id=1, username="default")
    db_session.add(meta)
    db_session.add_all(
        [
            make_identity(identity_id=1, acct="first@example.social"),
            make_identity(identity_id=2, acct="second@example.social"),
        ]
    )
    await db_session.commit()

    sync_friends_mock = AsyncMock()
    sync_blog_roll_mock = AsyncMock()
    sync_timeline_mock = AsyncMock(
        side_effect=[
            {"status": "success", "count": 3},
            {"status": "success", "count": 5},
        ]
    )
    sync_notifications_mock = AsyncMock(
        side_effect=[
            {"mentions": 1},
            {"mentions": 2},
        ]
    )

    with (
        patch.object(queries, "sync_friends_for_identity", sync_friends_mock),
        patch.object(queries, "sync_blog_roll_for_identity", sync_blog_roll_mock),
        patch.object(queries, "sync_user_timeline_for_identity", sync_timeline_mock),
        patch(
            "mastodon_is_my_blog.notification_sync.sync_notifications_for_identity",
            sync_notifications_mock,
        ),
    ):
        result = await queries.sync_all_identities(meta, force=True)

    assert result == [
        {
            "first@example.social": {
                "timeline": {"status": "success", "count": 3},
                "notifications": {"mentions": 1},
            }
        },
        {
            "second@example.social": {
                "timeline": {"status": "success", "count": 5},
                "notifications": {"mentions": 2},
            }
        },
    ]


@pytest.mark.asyncio
async def test_sync_friends_for_identity_persists_following_and_followers(
    db_session,
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(queries)
    db_session.add(make_meta_account())
    identity = make_identity()
    db_session.add(identity)
    await db_session.commit()

    client = MagicMock()
    client.account_verify_credentials.return_value = {"id": "me-1"}
    client.account_following.return_value = [
        make_account_data("following-1", acct="following@example.social")
    ]
    client.account_followers.return_value = [
        make_account_data("follower-1", acct="follower@example.social")
    ]

    with patch.object(queries, "client_from_identity", return_value=client):
        await queries.sync_friends_for_identity(1, identity)

    async with db_session_factory() as session:
        accounts = (
            await session.execute(
                select(store.CachedAccount).order_by(store.CachedAccount.id)
            )
        ).scalars().all()

    assert [(account.id, account.is_following, account.is_followed_by) for account in accounts] == [
        ("follower-1", False, True),
        ("following-1", True, False),
    ]


@pytest.mark.asyncio
async def test_sync_friends_for_identity_reraises_client_errors() -> None:
    identity = make_identity()
    client = MagicMock()
    client.account_verify_credentials.return_value = {"id": "me-1"}
    client.account_following.side_effect = RuntimeError("boom")

    with patch.object(queries, "client_from_identity", return_value=client):
        with pytest.raises(RuntimeError, match="boom"):
            await queries.sync_friends_for_identity(1, identity)


@pytest.mark.asyncio
async def test_sync_blog_roll_for_identity_updates_account_activity_stats(
    db_session,
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(queries)
    db_session.add(make_meta_account())
    identity = make_identity()
    db_session.add(identity)
    db_session.add_all(
        [
            make_cached_post(
                post_id="post-1",
                author_id="author-1",
                author_acct="author@example.social",
                is_reply=False,
            ),
            make_cached_post(
                post_id="post-2",
                author_id="author-1",
                author_acct="author@example.social",
                is_reply=True,
                in_reply_to_id="post-1",
            ),
        ]
    )
    await db_session.commit()

    home_status = {
        "account": make_account_data("author-1", acct="author@example.social"),
        "created_at": datetime(2024, 2, 1, tzinfo=timezone.utc),
    }
    client = MagicMock()
    client.timeline_home.return_value = [home_status]

    with patch.object(queries, "client_from_identity", return_value=client):
        await queries.sync_blog_roll_for_identity(1, identity)

    async with db_session_factory() as session:
        account = (
            await session.execute(
                select(store.CachedAccount).where(store.CachedAccount.id == "author-1")
            )
        ).scalar_one()

    assert account.last_status_at == datetime(2024, 2, 1, 0, 0)
    assert account.cached_post_count == 2
    assert account.cached_reply_count == 1


@pytest.mark.asyncio
async def test_sync_blog_roll_for_identity_reraises_errors() -> None:
    identity = make_identity()
    client = MagicMock()
    client.timeline_home.side_effect = RuntimeError("boom")

    with patch.object(queries, "client_from_identity", return_value=client):
        with pytest.raises(RuntimeError, match="boom"):
            await queries.sync_blog_roll_for_identity(1, identity)


@pytest.mark.asyncio
async def test_sync_user_timeline_for_identity_persists_self_timeline(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(queries, store)
    db_session.add(make_meta_account())
    identity = make_identity()
    db_session.add(identity)
    await db_session.commit()

    target_account = make_account_data("self-1", acct="me@example.social")
    statuses = [make_status("status-1", account_id="self-1", acct="me@example.social")]
    client = MagicMock()
    client.account_verify_credentials.return_value = target_account
    client.account_statuses.return_value = statuses

    with (
        patch.object(queries, "get_last_sync", AsyncMock(return_value=None)),
        patch.object(queries, "client_from_identity", return_value=client),
        patch.object(
            queries,
            "analyze_content_domains",
            return_value={
                "has_media": False,
                "has_video": False,
                "has_news": False,
                "has_tech": False,
                "has_link": False,
                "has_question": False,
            },
        ),
    ):
        result = await queries.sync_user_timeline_for_identity(1, identity)

    assert result == {"status": "success", "count": 1}
    assert await store.get_last_sync("timeline:1:1:self") is not None


@pytest.mark.asyncio
async def test_sync_user_timeline_for_identity_deep_syncs_search_result(
    db_session,
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(queries, store)
    db_session.add(make_meta_account())
    identity = make_identity()
    db_session.add(identity)
    await db_session.commit()

    target_account = make_account_data("friend-1", acct="friend@example.social")
    page_one = [make_status("status-1", account_id="friend-1", acct="friend@example.social")]
    page_two = [make_status("status-2", account_id="friend-1", acct="friend@example.social")]

    async def fake_deep_fetch(*args, **kwargs):
        yield page_one
        yield page_two

    client = MagicMock()
    client.account_search.return_value = [target_account]

    with (
        patch.object(queries, "get_last_sync", AsyncMock(return_value=None)),
        patch.object(queries, "client_from_identity", return_value=client),
        patch(
            "mastodon_is_my_blog.catchup.get_stop_at_id",
            AsyncMock(return_value="stop-1"),
        ),
        patch(
            "mastodon_is_my_blog.catchup.deep_fetch_user_timeline",
            fake_deep_fetch,
        ),
        patch.object(
            queries,
            "analyze_content_domains",
            return_value={
                "has_media": False,
                "has_video": False,
                "has_news": False,
                "has_tech": False,
                "has_link": False,
                "has_question": False,
            },
        ),
    ):
        result = await queries.sync_user_timeline_for_identity(
            1,
            identity,
            acct="friend@example.social",
            deep=True,
            max_pages=2,
            rate_budget="shared-budget",
        )

    async with db_session_factory() as session:
        post_count = (
            await session.execute(select(func.count()).select_from(store.CachedPost))
        ).scalar_one()

    assert result == {"status": "success", "count": 2}
    assert post_count == 2


@pytest.mark.asyncio
async def test_sync_user_timeline_for_identity_returns_error_payload_on_failure() -> None:
    identity = make_identity()
    client = MagicMock()
    client.account_verify_credentials.side_effect = RuntimeError("boom")

    with (
        patch.object(queries, "get_last_sync", AsyncMock(return_value=None)),
        patch.object(queries, "client_from_identity", return_value=client),
    ):
        result = await queries.sync_user_timeline_for_identity(1, identity)

    assert result == {"status": "error", "msg": "boom"}


@pytest.mark.asyncio
async def test_sync_accounts_friends_followers_handles_missing_prerequisites(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(queries)

    with patch.object(queries, "get_token", AsyncMock(return_value=None)):
        assert await queries.sync_accounts_friends_followers() is None

    with patch.object(queries, "get_token", AsyncMock(return_value="token")):
        assert await queries.sync_accounts_friends_followers() is None

    db_session.add(make_meta_account())
    await db_session.commit()

    with patch.object(queries, "get_token", AsyncMock(return_value="token")):
        assert await queries.sync_accounts_friends_followers() is None


@pytest.mark.asyncio
async def test_sync_accounts_friends_followers_runs_sync_for_default_identity(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(queries)
    db_session.add(make_meta_account())
    identity = make_identity()
    db_session.add(identity)
    await db_session.commit()

    with (
        patch.object(queries, "get_token", AsyncMock(return_value="token")),
        patch.object(queries, "sync_friends_for_identity", AsyncMock()) as sync_mock,
        patch.object(queries, "update_last_sync", AsyncMock()) as update_mock,
    ):
        await queries.sync_accounts_friends_followers()

    sync_mock.assert_awaited_once()
    synced_identity = sync_mock.await_args.args[1]
    assert sync_mock.await_args.args[0] == 1
    assert synced_identity.id == identity.id
    assert synced_identity.acct == identity.acct
    update_mock.assert_awaited_once_with("accounts")


@pytest.mark.asyncio
async def test_sync_blog_roll_activity_handles_missing_prerequisites(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(queries)
    assert await queries.sync_blog_roll_activity() is None

    db_session.add(make_meta_account())
    await db_session.commit()

    assert await queries.sync_blog_roll_activity() is None


@pytest.mark.asyncio
async def test_sync_blog_roll_activity_runs_for_default_identity(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(queries)
    db_session.add(make_meta_account())
    identity = make_identity()
    db_session.add(identity)
    await db_session.commit()

    with patch.object(queries, "sync_blog_roll_for_identity", AsyncMock()) as sync_mock:
        await queries.sync_blog_roll_activity()

    sync_mock.assert_awaited_once()
    synced_identity = sync_mock.await_args.args[1]
    assert sync_mock.await_args.args[0] == 1
    assert synced_identity.id == identity.id
    assert synced_identity.acct == identity.acct


@pytest.mark.asyncio
async def test_sync_user_timeline_raises_when_default_identity_missing(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(queries)
    db_session.add(make_meta_account())
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await queries.sync_user_timeline()

    assert exc_info.value.detail == "No identity found"


@pytest.mark.asyncio
async def test_sync_user_timeline_delegates_to_identity_specific_helper(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(queries)
    db_session.add(make_meta_account())
    identity = make_identity()
    db_session.add(identity)
    await db_session.commit()

    timeline_mock = AsyncMock(return_value={"status": "success", "count": 7})
    with patch.object(queries, "sync_user_timeline_for_identity", timeline_mock):
        result = await queries.sync_user_timeline(
            acct="friend@example.social",
            force=True,
        )

    assert result == {"status": "success", "count": 7}
    timeline_mock.assert_awaited_once()
    awaited_kwargs = timeline_mock.await_args.kwargs
    assert awaited_kwargs["meta_id"] == 1
    assert awaited_kwargs["acct"] == "friend@example.social"
    assert awaited_kwargs["force"] is True
    assert awaited_kwargs["identity"].id == identity.id
    assert awaited_kwargs["identity"].acct == identity.acct
