"""Tests for follow/unfollow actions.

The mastodon.social admin persona cares that write actions hit the right
account: Mastodon's account_search is fuzzy, so acting on the first result
without verifying it can follow a total stranger.
"""

import pytest
from fastapi import HTTPException

import mastodon_is_my_blog.mastodon_apis.follow_actions as follow_actions
from mastodon_is_my_blog.mastodon_apis.follow_actions import (
    acct_matches,
    follow_account,
    unfollow_account,
)
from test.conftest import make_cached_account, make_identity, make_meta_account


class FakeClient:
    def __init__(self, search_results=None, fail_search=False, fail_follow=False):
        self.search_results = search_results or []
        self.fail_search = fail_search
        self.fail_follow = fail_follow
        self.followed: list[str] = []
        self.unfollowed: list[str] = []

    def account_search(self, q, limit=1):
        if self.fail_search:
            raise RuntimeError("boom")
        return self.search_results

    def account_follow(self, account_id):
        if self.fail_follow:
            raise RuntimeError("boom")
        self.followed.append(account_id)

    def account_unfollow(self, account_id):
        self.unfollowed.append(account_id)


@pytest.fixture
def fake_env(monkeypatch, patch_async_session):
    patch_async_session(follow_actions)

    def install(client: FakeClient):
        monkeypatch.setattr(follow_actions, "client_from_identity", lambda identity: client)
        return client

    return install


async def seed(db_session, *, is_following: bool):
    db_session.add(make_meta_account())
    db_session.add(make_identity())
    db_session.add(make_cached_account("remote-42", acct="friend@example.social", is_following=is_following))
    await db_session.commit()


class TestAcctMatches:
    def test_exact_match(self):
        assert acct_matches("friend@example.social", "friend@example.social")

    def test_case_and_at_prefix_insensitive(self):
        assert acct_matches("@Friend@Example.Social", "friend@example.social")

    def test_local_account_without_domain(self):
        assert acct_matches("friend", "friend@example.social")
        assert acct_matches("friend@example.social", "friend")

    def test_different_account_rejected(self):
        assert not acct_matches("friend@example.social", "fiend@example.social")

    def test_same_name_different_instance_rejected(self):
        assert not acct_matches("friend@example.social", "friend@evil.example")


class TestFollowAccount:
    @pytest.mark.asyncio
    async def test_follows_and_updates_cache(self, fake_env, db_session):
        await seed(db_session, is_following=False)
        client = fake_env(FakeClient([{"id": "remote-42", "acct": "friend@example.social"}]))

        result = await follow_account(1, make_identity(), "friend@example.social")

        assert result == {"followed": True, "acct": "friend@example.social"}
        assert client.followed == ["remote-42"]
        account = await db_session.get(follow_actions.CachedAccount, ("remote-42", 1, 1))
        assert account.is_following is True

    @pytest.mark.asyncio
    async def test_wrong_search_result_is_not_followed(self, fake_env, db_session):
        """Regression: fuzzy search returning a different account must 404,
        not follow the stranger."""
        await seed(db_session, is_following=False)
        client = fake_env(FakeClient([{"id": "stranger-1", "acct": "somebody@else.example"}]))

        with pytest.raises(HTTPException) as exc:
            await follow_account(1, make_identity(), "friend@example.social")

        assert exc.value.status_code == 404
        assert client.followed == []

    @pytest.mark.asyncio
    async def test_empty_search_is_404(self, fake_env, db_session):
        await seed(db_session, is_following=False)
        fake_env(FakeClient([]))
        with pytest.raises(HTTPException) as exc:
            await follow_account(1, make_identity(), "friend@example.social")
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_search_api_error_is_502(self, fake_env, db_session):
        await seed(db_session, is_following=False)
        fake_env(FakeClient(fail_search=True))
        with pytest.raises(HTTPException) as exc:
            await follow_account(1, make_identity(), "friend@example.social")
        assert exc.value.status_code == 502

    @pytest.mark.asyncio
    async def test_follow_api_error_is_502(self, fake_env, db_session):
        await seed(db_session, is_following=False)
        fake_env(
            FakeClient(
                [{"id": "remote-42", "acct": "friend@example.social"}],
                fail_follow=True,
            )
        )
        with pytest.raises(HTTPException) as exc:
            await follow_account(1, make_identity(), "friend@example.social")
        assert exc.value.status_code == 502


class TestUnfollowAccount:
    @pytest.mark.asyncio
    async def test_unfollows_and_updates_cache(self, fake_env, db_session):
        await seed(db_session, is_following=True)
        client = fake_env(FakeClient([{"id": "remote-42", "acct": "friend@example.social"}]))

        result = await unfollow_account(1, make_identity(), "friend@example.social")

        assert result == {"unfollowed": True, "acct": "friend@example.social"}
        assert client.unfollowed == ["remote-42"]
        account = await db_session.get(follow_actions.CachedAccount, ("remote-42", 1, 1))
        assert account.is_following is False
