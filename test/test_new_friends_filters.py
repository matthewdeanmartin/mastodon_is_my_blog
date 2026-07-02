"""Tests for the new-friends candidate filtering and cache freshness logic."""

import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import mastodon_is_my_blog.routes.new_friends as new_friends
from mastodon_is_my_blog.datetime_helpers import utc_now
from mastodon_is_my_blog.routes.new_friends import (
    _apply_filters,
    _fetch_and_cache,
    _is_cache_fresh,
    strip_html,
)
from mastodon_is_my_blog.store import FriendsOfFriendsCache
from test.conftest import (
    make_cached_account,
    make_cached_notification,
    make_identity,
    make_meta_account,
)


def make_candidate(
    candidate_id: str = "c1",
    *,
    statuses_count=25,
    last_status_at: str | None = None,
    note: str = "",
) -> dict:
    return {
        "id": candidate_id,
        "acct": f"{candidate_id}@example.social",
        "statuses_count": statuses_count,
        "last_status_at": last_status_at,
        "note": note,
    }


class TestStripHtml:
    def test_removes_tags(self):
        assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_none_and_empty(self):
        assert strip_html("") == ""
        assert strip_html(None) == ""


class TestIsCacheFresh:
    def test_none_is_stale(self):
        assert _is_cache_fresh(None) is False

    def test_recent_is_fresh(self):
        assert _is_cache_fresh(utc_now() - timedelta(hours=1)) is True

    def test_old_is_stale(self):
        assert _is_cache_fresh(utc_now() - timedelta(hours=7)) is False


class TestApplyFilters:
    def test_excludes_already_following(self):
        candidates = [make_candidate("c1"), make_candidate("c2")]
        result = _apply_filters(candidates, {"c1"}, 0, 365, "")
        assert [c["id"] for c in result] == ["c2"]

    def test_min_posts(self):
        candidates = [
            make_candidate("quiet", statuses_count=2),
            make_candidate("chatty", statuses_count=200),
        ]
        result = _apply_filters(candidates, set(), 10, 365, "")
        assert [c["id"] for c in result] == ["chatty"]

    def test_none_statuses_count_does_not_crash(self):
        """Regression: instances can return null statuses_count; the filter
        used to raise TypeError comparing None < int."""
        candidates = [make_candidate("mystery", statuses_count=None)]
        assert _apply_filters(candidates, set(), 0, 365, "") == candidates
        assert _apply_filters(candidates, set(), 5, 365, "") == []

    def test_inactive_accounts_dropped(self):
        stale = (utc_now() - timedelta(days=400)).isoformat()
        fresh = (utc_now() - timedelta(days=5)).isoformat()
        candidates = [
            make_candidate("stale", last_status_at=stale),
            make_candidate("fresh", last_status_at=fresh),
            make_candidate("unknown", last_status_at=None),
        ]
        result = _apply_filters(candidates, set(), 0, 30, "")
        # Unknown activity is kept (benefit of the doubt), stale is dropped.
        assert [c["id"] for c in result] == ["fresh", "unknown"]

    def test_unparseable_last_status_at_is_kept(self):
        candidates = [make_candidate("weird", last_status_at="not-a-date")]
        assert _apply_filters(candidates, set(), 0, 30, "") == candidates

    def test_bio_filter_case_insensitive(self):
        candidates = [
            make_candidate("py", note="I write Python all day"),
            make_candidate("js", note="JavaScript forever"),
        ]
        result = _apply_filters(candidates, set(), 0, 365, "python")
        assert [c["id"] for c in result] == ["py"]


class FakeClient:
    """Records which friends were expanded and returns canned followings."""

    def __init__(self, following_by_id: dict[str, list[dict]] | None = None):
        self.following_by_id = following_by_id or {}
        self.expanded: list[str] = []

    def account_following(self, account_id, limit=80):
        self.expanded.append(account_id)
        return self.following_by_id.get(account_id, [])


async def seed_blogroll(db_session):
    """One friend per blogroll category, most recently active first."""
    db_session.add(make_meta_account())
    db_session.add(make_identity())
    top_friend = make_cached_account(
        "tf-1",
        acct="topfriend@example.social",
        is_followed_by=True,
        last_status_at=datetime(2026, 6, 4),
    )
    mutual = make_cached_account(
        "mu-1",
        acct="mutual@example.social",
        is_followed_by=True,
        last_status_at=datetime(2026, 6, 3),
    )
    bot = make_cached_account(
        "bot-1", acct="bot@example.social", last_status_at=datetime(2026, 6, 2)
    )
    bot.bot = True
    follow_only = make_cached_account(
        "fo-1", acct="quiet@example.social", last_status_at=datetime(2026, 6, 1)
    )
    db_session.add_all([top_friend, mutual, bot, follow_only])
    db_session.add(
        make_cached_notification(
            "notif-1", notification_type="favourite", account_id="tf-1"
        )
    )
    await db_session.commit()


class TestFetchAndCacheBlogrollFilter:
    @pytest.fixture(autouse=True)
    def env(self, monkeypatch, patch_async_session):
        patch_async_session(new_friends)
        self.client = FakeClient(
            {
                "tf-1": [
                    {"id": "cand-1", "acct": "newperson@example.social"},
                    {"id": "mu-1", "acct": "mutual@example.social"},  # already followed
                ]
            }
        )
        monkeypatch.setattr(
            new_friends, "client_from_identity", lambda identity: self.client
        )

    @pytest.mark.asyncio
    async def test_no_filter_expands_all_follows_most_active_first(self, db_session):
        await seed_blogroll(db_session)
        await _fetch_and_cache(
            1, make_identity(), max_friends=50, blog_roll_filter=None
        )
        assert self.client.expanded == ["tf-1", "mu-1", "bot-1", "fo-1"]

    @pytest.mark.asyncio
    async def test_top_friends_filter_expands_only_top_friends(self, db_session):
        await seed_blogroll(db_session)
        candidates = await _fetch_and_cache(
            1, make_identity(), max_friends=50, blog_roll_filter="top_friends"
        )
        assert self.client.expanded == ["tf-1"]
        # Already-followed accounts are excluded even when sources are filtered
        assert [c["id"] for c in candidates] == ["cand-1"]

    @pytest.mark.asyncio
    async def test_mutuals_filter_excludes_top_friends_and_bots(self, db_session):
        await seed_blogroll(db_session)
        await _fetch_and_cache(
            1, make_identity(), max_friends=50, blog_roll_filter="mutuals"
        )
        assert self.client.expanded == ["mu-1"]

    @pytest.mark.asyncio
    async def test_bots_filter(self, db_session):
        await seed_blogroll(db_session)
        await _fetch_and_cache(
            1, make_identity(), max_friends=50, blog_roll_filter="bots"
        )
        assert self.client.expanded == ["bot-1"]

    @pytest.mark.asyncio
    async def test_unknown_filter_is_400_with_no_api_calls(self, db_session):
        await seed_blogroll(db_session)
        with pytest.raises(HTTPException) as exc:
            await _fetch_and_cache(
                1, make_identity(), max_friends=50, blog_roll_filter="besties"
            )
        assert exc.value.status_code == 400
        assert self.client.expanded == []

    @pytest.mark.asyncio
    async def test_max_friends_caps_filtered_expansion(self, db_session):
        await seed_blogroll(db_session)
        await _fetch_and_cache(1, make_identity(), max_friends=2, blog_roll_filter=None)
        assert self.client.expanded == ["tf-1", "mu-1"]

    @pytest.mark.asyncio
    async def test_results_are_cached(self, db_session):
        await seed_blogroll(db_session)
        await _fetch_and_cache(
            1, make_identity(), max_friends=50, blog_roll_filter="top_friends"
        )
        cached = (
            await db_session.execute(
                select(FriendsOfFriendsCache).where(
                    FriendsOfFriendsCache.identity_id == 1
                )
            )
        ).scalar_one()
        assert [c["id"] for c in json.loads(cached.data_json)] == ["cand-1"]

    @pytest.mark.asyncio
    async def test_timed_scan_checkpoints_and_resumes(self, db_session):
        await seed_blogroll(db_session)

        first = await _fetch_and_cache(
            1,
            make_identity(),
            max_friends=2,
            blog_roll_filter=None,
            max_duration_seconds=0,
        )
        assert first == []
        checkpoint = (
            await db_session.execute(
                select(FriendsOfFriendsCache).where(
                    FriendsOfFriendsCache.identity_id == 1
                )
            )
        ).scalar_one()
        await db_session.refresh(checkpoint)
        assert checkpoint.scan_complete is False
        assert checkpoint.next_friend_index == 0

        await _fetch_and_cache(
            1,
            make_identity(),
            max_friends=2,
            blog_roll_filter=None,
            max_duration_seconds=30,
        )
        await db_session.refresh(checkpoint)
        assert checkpoint.scan_complete is True
        assert checkpoint.next_friend_index == 2
        assert self.client.expanded == ["tf-1", "mu-1"]
