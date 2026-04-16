import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from mastodon_is_my_blog import queries
from mastodon_is_my_blog.datetime_helpers import utc_now
from mastodon_is_my_blog.store import CachedAccount, CachedPost, SeenPost
from test.conftest import (
    make_account_data,
    make_cached_account,
    make_cached_post,
    make_identity,
    make_meta_account,
    make_status,
)


@pytest.mark.asyncio
async def test_get_current_meta_account_prefers_header_and_falls_back_default(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(queries)
    db_session.add_all(
        [
            make_meta_account(meta_id=1, username="default"),
            make_meta_account(meta_id=2, username="secondary"),
        ]
    )
    await db_session.commit()

    header_request = Request(
        {"type": "http", "headers": [(b"x-meta-account-id", b"2")]}
    )
    fallback_request = Request({"type": "http", "headers": []})

    assert (await queries.get_current_meta_account(header_request)).id == 2
    assert (await queries.get_current_meta_account(fallback_request)).id == 1


def test_build_account_payload_applies_defaults_and_overrides() -> None:
    payload = queries.build_account_payload(
        make_account_data(
            "account-1",
            acct="friend@example.social",
            created_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
        ),
        is_following=True,
    )

    assert payload["acct"] == "friend@example.social"
    assert payload["created_at"] == datetime(2024, 1, 2)
    assert json.loads(payload["fields"]) == []
    assert payload["is_following"] is True


@pytest.mark.asyncio
async def test_bulk_upsert_accounts_merges_duplicates_and_latest_status(
    db_session,
    db_session_factory,
) -> None:
    existing = make_cached_account(
        account_id="account-1",
        acct="friend@example.social",
        last_status_at=datetime(2024, 1, 2),
    )
    existing.is_followed_by = True
    db_session.add(existing)
    await db_session.commit()

    await queries.bulk_upsert_accounts(
        db_session,
        1,
        1,
        [
            {
                "account_data": make_account_data("account-1", acct="friend@example.social"),
                "last_status_at": datetime(2024, 1, 3, tzinfo=timezone.utc),
            },
            {
                "account_data": make_account_data(
                    "account-1",
                    acct="updated@example.social",
                    display_name="Updated",
                ),
                "last_status_at": datetime(2024, 1, 1),
            },
        ],
    )
    await db_session.commit()

    async with db_session_factory() as session:
        stored = (
            await session.execute(
                select(CachedAccount).where(CachedAccount.id == "account-1")
            )
        ).scalar_one()

    assert stored.acct == "updated@example.social"
    assert stored.display_name == "Updated"
    assert stored.last_status_at == datetime(2024, 1, 3)
    assert stored.is_followed_by is True


def test_build_post_payload_handles_reblogs_and_reply_flags() -> None:
    reblogged_status = make_status(
        "boost-source",
        account_id="author-1",
        acct="author@example.social",
        content="<p>original</p>",
        in_reply_to_id="root-1",
        in_reply_to_account_id="other-author",
        media_attachments=[{"type": "image", "url": "https://example.social/image.jpg"}],
    )
    boosted = make_status(
        "boost-wrapper",
        account_id="booster-1",
        acct="booster@example.social",
        reblog=reblogged_status,
        tags=[{"name": "python"}],
    )

    with patch.object(
        queries,
        "analyze_content_domains",
        return_value={
            "has_media": True,
            "has_video": False,
            "has_news": False,
            "has_tech": True,
            "has_link": True,
            "has_question": False,
        },
    ):
        payload = queries.build_post_payload(1, 2, boosted)

    assert payload["id"] == "boost-wrapper"
    assert payload["author_acct"] == "author@example.social"
    assert payload["is_reblog"] is True
    assert payload["is_reply"] is True
    assert payload["in_reply_to_id"] == "root-1"
    assert payload["media_attachments"] is not None
    assert json.loads(payload["tags"]) == ["python"]
    assert payload["has_tech"] is True


@pytest.mark.asyncio
async def test_bulk_upsert_posts_returns_new_and_updated_counts(db_session) -> None:
    existing = make_cached_post(post_id="post-1", content="<p>old</p>")
    db_session.add(existing)
    await db_session.commit()

    with patch.object(
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
    ):
        result = await queries.bulk_upsert_posts(
            db_session,
            1,
            1,
            [
                make_status("post-1", content="<p>updated</p>"),
                make_status("post-2", content="<p>new</p>"),
                make_status("post-2", content="<p>newest</p>"),
            ],
        )
    await db_session.commit()

    stored = (
        await db_session.execute(select(CachedPost).where(CachedPost.id == "post-2"))
    ).scalar_one()

    assert result == (1, 1)
    assert stored.content == "<p>newest</p>"


@pytest.mark.asyncio
async def test_upsert_account_returns_persisted_row(db_session) -> None:
    stored = await queries._upsert_account(
        db_session,
        1,
        1,
        make_account_data("account-7", acct="seven@example.social"),
        is_following=True,
    )

    assert stored.id == "account-7"
    assert stored.is_following is True


@pytest.mark.asyncio
async def test_get_counts_optimized_returns_totals_and_unseen(db_session) -> None:
    db_session.add_all(
        [
            make_cached_post(
                post_id="short-1",
                content="short post",
            ),
            make_cached_post(
                post_id="storm-1",
                content="x" * 700,
            ),
            make_cached_post(
                post_id="news-1",
                has_news=True,
                content="news",
            ),
            make_cached_post(
                post_id="reply-1",
                is_reply=True,
                in_reply_to_id="root-1",
                content="reply",
            ),
            SeenPost(meta_account_id=1, post_id="short-1"),
        ]
    )
    await db_session.commit()

    stats = await queries.get_counts_optimized(db_session, 1, 1)

    assert stats["user"] == "all"
    assert stats["everyone"] == {"total": 4, "unseen": 3}
    assert stats["shorts"] == {"total": 2, "unseen": 1}
    assert stats["storms"] == {"total": 1, "unseen": 1}
    assert stats["news"] == {"total": 1, "unseen": 1}
    assert stats["discussions"] == {"total": 1, "unseen": 1}


@pytest.mark.asyncio
async def test_sync_user_timeline_for_identity_skips_recent_cooldown() -> None:
    identity = make_identity()

    with patch.object(
        queries,
        "get_last_sync",
        AsyncMock(return_value=utc_now() - timedelta(minutes=5)),
    ):
        result = await queries.sync_user_timeline_for_identity(
            1,
            identity,
            force=False,
            cooldown_minutes=15,
        )

    assert result == {"status": "skipped"}


@pytest.mark.asyncio
async def test_sync_user_timeline_for_identity_returns_not_found_for_unknown_account() -> None:
    identity = make_identity()
    client = MagicMock()
    client.account_search.return_value = []

    with (
        patch.object(queries, "get_last_sync", AsyncMock(return_value=None)),
        patch.object(queries, "client_from_identity", return_value=client),
    ):
        result = await queries.sync_user_timeline_for_identity(
            1,
            identity,
            acct="missing@example.social",
        )

    assert result == {"status": "not_found"}


@pytest.mark.asyncio
async def test_sync_user_timeline_returns_virtual_user_skip() -> None:
    result = await queries.sync_user_timeline(acct="everyone")

    assert result == {"status": "skipped", "reason": "virtual_user"}


@pytest.mark.asyncio
async def test_sync_user_timeline_raises_when_default_meta_missing(
    patch_async_session,
) -> None:
    patch_async_session(queries)

    with pytest.raises(HTTPException) as exc_info:
        await queries.sync_user_timeline()

    assert exc_info.value.detail == "Default meta account missing"
