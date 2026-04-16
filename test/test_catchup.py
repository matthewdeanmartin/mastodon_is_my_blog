"""
Unit tests for catchup.py — 4.2 get_catchup_queue and 4.3 deep_fetch_user_timeline.

All tests use in-memory SQLite and unittest.mock; no live API calls.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mastodon_is_my_blog.datetime_helpers import utc_now
from mastodon_is_my_blog.store import Base, CachedAccount, CachedNotification, CachedPost


# ---------------------------------------------------------------------------
# Shared in-memory DB fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

META_ID = 1
IDENTITY_ID = 1


def make_account(
    acc_id: str,
    *,
    is_following: bool = True,
    is_followed_by: bool = False,
    last_status_at: datetime | None = None,
) -> CachedAccount:
    return CachedAccount(
        id=acc_id,
        meta_account_id=META_ID,
        mastodon_identity_id=IDENTITY_ID,
        acct=f"{acc_id}@example.com",
        display_name=acc_id,
        avatar="",
        url="",
        note="",
        bot=False,
        locked=False,
        header="",
        fields="[]",
        followers_count=0,
        following_count=0,
        statuses_count=0,
        is_following=is_following,
        is_followed_by=is_followed_by,
        last_status_at=last_status_at,
        cached_post_count=0,
        cached_reply_count=0,
    )


def make_notification(notif_id: str, account_id: str, created_at: datetime) -> CachedNotification:
    return CachedNotification(
        id=notif_id,
        meta_account_id=META_ID,
        identity_id=IDENTITY_ID,
        type="mention",
        created_at=created_at,
        account_id=account_id,
        account_acct=f"{account_id}@example.com",
        status_id=None,
    )


# ---------------------------------------------------------------------------
# 4.2  get_catchup_queue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_queue_only_includes_following(db) -> None:
    """Accounts with is_following=False must not appear in the queue."""
    db.add(make_account("follower-only", is_following=False, is_followed_by=True))
    db.add(make_account("following", is_following=True, is_followed_by=False))
    await db.flush()

    with patch("mastodon_is_my_blog.catchup.async_session") as mock_session_ctx:
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        from mastodon_is_my_blog.catchup import get_catchup_queue
        result = await get_catchup_queue(META_ID, IDENTITY_ID)

    acct_ids = [a.id for a in result]
    assert "following" in acct_ids
    assert "follower-only" not in acct_ids


@pytest.mark.asyncio
async def test_mutual_with_notification_ranks_first(db) -> None:
    """Priority 1 (mutual + notification) beats priority 2 (mutual) and priority 3."""
    recent = utc_now() - timedelta(days=5)
    old = utc_now() - timedelta(days=60)

    db.add(make_account("plain-follow", is_following=True, last_status_at=recent))
    db.add(make_account("mutual", is_following=True, is_followed_by=True, last_status_at=recent))
    db.add(make_account("mutual-notif", is_following=True, is_followed_by=True, last_status_at=recent))
    db.add(make_notification("n1", "mutual-notif", recent))
    await db.flush()

    with patch("mastodon_is_my_blog.catchup.async_session") as mock_session_ctx:
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        from mastodon_is_my_blog.catchup import get_catchup_queue
        result = await get_catchup_queue(META_ID, IDENTITY_ID)

    ids = [a.id for a in result]
    assert ids[0] == "mutual-notif", f"Expected mutual-notif first, got {ids}"
    assert "mutual" in ids
    assert "plain-follow" in ids


@pytest.mark.asyncio
async def test_max_accounts_limits_result(db) -> None:
    for i in range(5):
        db.add(make_account(f"acc-{i}", is_following=True))
    await db.flush()

    with patch("mastodon_is_my_blog.catchup.async_session") as mock_session_ctx:
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        from mastodon_is_my_blog.catchup import get_catchup_queue
        result = await get_catchup_queue(META_ID, IDENTITY_ID, max_accounts=3)

    assert len(result) == 3


@pytest.mark.asyncio
async def test_empty_queue_when_no_following(db) -> None:
    db.add(make_account("stranger", is_following=False, is_followed_by=True))
    await db.flush()

    with patch("mastodon_is_my_blog.catchup.async_session") as mock_session_ctx:
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        from mastodon_is_my_blog.catchup import get_catchup_queue
        result = await get_catchup_queue(META_ID, IDENTITY_ID)

    assert result == []


# ---------------------------------------------------------------------------
# 4.3  deep_fetch_user_timeline
# ---------------------------------------------------------------------------

def _make_status(sid: str) -> dict:
    return {
        "id": sid,
        "reblog": None,
        "content": "<p>test</p>",
        "created_at": datetime(2024, 1, 1),
        "visibility": "public",
        "account": {"id": "111", "acct": "alice@example.com"},
        "in_reply_to_id": None,
        "in_reply_to_account_id": None,
        "media_attachments": [],
        "tags": [],
        "replies_count": 0,
        "reblogs_count": 0,
        "favourites_count": 0,
    }


def _make_mock_mastodon(pages: list[list[dict]]) -> MagicMock:
    """Return a MagicMock Mastodon client whose account_statuses returns pages in sequence."""
    m = MagicMock()
    m.account_statuses.side_effect = pages + [[]]  # final empty page to signal end
    return m


@pytest.mark.asyncio
async def test_deep_fetch_yields_all_pages() -> None:
    """All non-empty pages are yielded."""
    pages = [
        [_make_status(str(i)) for i in range(40, 80)],   # page 1: ids 40-79
        [_make_status(str(i)) for i in range(0, 40)],    # page 2: ids 0-39
    ]
    m = _make_mock_mastodon(pages)

    from mastodon_is_my_blog.catchup import deep_fetch_user_timeline

    collected: list[list[dict]] = []
    async for page in deep_fetch_user_timeline(m, "111", inter_page_delay=0):
        collected.append(page)

    assert len(collected) == 2
    assert len(collected[0]) == 40
    assert len(collected[1]) == 40


@pytest.mark.asyncio
async def test_deep_fetch_stops_at_stop_id() -> None:
    """Pages where all ids <= stop_at_id are skipped and iteration ends."""
    pages = [
        [_make_status("100"), _make_status("90")],  # page 1: above stop
        [_make_status("50"), _make_status("40")],   # page 2: all <= "60" — should stop
    ]
    m = _make_mock_mastodon(pages)

    from mastodon_is_my_blog.catchup import deep_fetch_user_timeline

    collected: list[list[dict]] = []
    async for page in deep_fetch_user_timeline(m, "111", stop_at_id="60", inter_page_delay=0):
        collected.append(page)

    assert len(collected) == 1
    assert collected[0][0]["id"] == "100"


@pytest.mark.asyncio
async def test_deep_fetch_respects_max_pages() -> None:
    """Iteration stops after max_pages regardless of remaining data."""
    # Return 40-item pages forever (side_effect cycles)
    m = MagicMock()
    m.account_statuses.return_value = [_make_status(str(i)) for i in range(40)]

    from mastodon_is_my_blog.catchup import deep_fetch_user_timeline

    collected: list[list[dict]] = []
    async for page in deep_fetch_user_timeline(m, "111", max_pages=3, inter_page_delay=0):
        collected.append(page)

    assert len(collected) == 3


@pytest.mark.asyncio
async def test_deep_fetch_stops_on_short_page() -> None:
    """A page shorter than 40 statuses signals no more history."""
    m = MagicMock()
    # First call: 40 statuses; second call: only 10 (short page)
    m.account_statuses.side_effect = [
        [_make_status(str(i)) for i in range(40, 80)],
        [_make_status(str(i)) for i in range(0, 10)],
    ]

    from mastodon_is_my_blog.catchup import deep_fetch_user_timeline

    collected: list[list[dict]] = []
    async for page in deep_fetch_user_timeline(m, "111", inter_page_delay=0):
        collected.append(page)

    assert len(collected) == 2
    assert len(collected[1]) == 10


@pytest.mark.asyncio
async def test_deep_fetch_calls_on_page_callback() -> None:
    """on_page callback is awaited for each page."""
    pages = [
        [_make_status(str(i)) for i in range(40, 80)],  # full page — continues
        [_make_status(str(i)) for i in range(0, 5)],    # short page — last
    ]
    m = _make_mock_mastodon(pages)

    received: list[list[dict]] = []

    async def on_page(page: list[dict]) -> None:
        received.append(page)

    from mastodon_is_my_blog.catchup import deep_fetch_user_timeline

    async for _ in deep_fetch_user_timeline(m, "111", on_page=on_page, inter_page_delay=0):
        pass

    assert len(received) == 2


@pytest.mark.asyncio
async def test_deep_fetch_retries_on_rate_limit() -> None:
    """On 429 (MastodonRatelimitError), sleeps and retries once."""
    from mastodon.errors import MastodonRatelimitError

    good_page = [_make_status("10")]
    rate_limited = MastodonRatelimitError("rate limited")
    rate_limited.retry_after = 0  # type: ignore[attr-defined]

    m = MagicMock()
    m.account_statuses.side_effect = [rate_limited, good_page, []]

    from mastodon_is_my_blog.catchup import deep_fetch_user_timeline

    collected: list[list[dict]] = []
    with patch("mastodon_is_my_blog.catchup.asyncio.sleep", new_callable=AsyncMock):
        async for page in deep_fetch_user_timeline(m, "111", inter_page_delay=0):
            collected.append(page)

    assert len(collected) == 1
    assert collected[0][0]["id"] == "10"


# ---------------------------------------------------------------------------
# get_stop_at_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_stop_at_id_returns_none_when_no_posts(db) -> None:
    with patch("mastodon_is_my_blog.catchup.async_session") as mock_session_ctx:
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        from mastodon_is_my_blog.catchup import get_stop_at_id
        result = await get_stop_at_id(META_ID, IDENTITY_ID, "alice@example.com")

    assert result is None


@pytest.mark.asyncio
async def test_get_stop_at_id_returns_max_post_id(db) -> None:
    for pid in ["100", "200", "150"]:
        db.add(CachedPost(
            id=pid,
            meta_account_id=META_ID,
            fetched_by_identity_id=IDENTITY_ID,
            content="<p>x</p>",
            created_at=datetime(2024, 1, 1),
            visibility="public",
            author_acct="alice@example.com",
            author_id="111",
            is_reblog=False,
            is_reply=False,
            has_media=False,
            has_video=False,
            has_news=False,
            has_tech=False,
            has_link=False,
            has_question=False,
            replies_count=0,
            reblogs_count=0,
            favourites_count=0,
            tags="[]",
        ))
    await db.flush()

    with patch("mastodon_is_my_blog.catchup.async_session") as mock_session_ctx:
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        from mastodon_is_my_blog.catchup import get_stop_at_id
        result = await get_stop_at_id(META_ID, IDENTITY_ID, "alice@example.com")

    assert result == "200"
