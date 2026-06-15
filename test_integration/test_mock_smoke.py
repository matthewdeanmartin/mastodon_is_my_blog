"""Smoke tests proving the mock behaves enough like Mastodon for the blog.

These drive the blog's own ``TimedMastodonClient`` wrapper (``blog_client``)
against the running mock, asserting on *shape and invariants* rather than
hardcoded ids, so the same assertions would hold against a real instance. The
write round-trip is the headline: it proves the mock is genuinely stateful.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from mastodon.errors import MastodonNotFoundError

from mastodon_is_my_blog.mastodon_apis.masto_client_timed import TimedMastodonClient


def test_verify_credentials_returns_the_seeded_account(
    blog_client: TimedMastodonClient,
) -> None:
    me = blog_client.account_verify_credentials()
    assert me.username == "alice"
    assert me.acct
    assert isinstance(me.created_at, datetime)


def test_home_timeline_is_non_empty_and_well_shaped(
    blog_client: TimedMastodonClient,
) -> None:
    home = blog_client.timeline_home(limit=10)
    assert isinstance(home, list)
    # alice follows bob, who has two seeded statuses.
    assert len(home) >= 2
    for status in home:
        assert status.id
        assert isinstance(status.created_at, datetime)
        assert isinstance(status.content, str)
        assert status.account is not None
        assert status.account.acct


def test_account_statuses_returns_the_authors_posts(
    blog_client: TimedMastodonClient,
) -> None:
    me = blog_client.account_verify_credentials()
    # Find bob (the followed author with seeded statuses) by his acct, rather
    # than assuming a timeline ordering — the session-scoped server accumulates
    # state across tests, so alice's own posts may sort ahead of bob's.
    home = blog_client.timeline_home(limit=40)
    bob_accounts = {s.account.id for s in home if s.account.acct == "bob"}
    assert bob_accounts, "bob should appear in alice's home timeline"
    bob_id = bob_accounts.pop()
    assert str(bob_id) != str(me.id)

    posts = blog_client.account_statuses(bob_id, limit=40)
    assert isinstance(posts, list)
    assert posts, "seeded author should have statuses"
    assert all(str(p.account.id) == str(bob_id) for p in posts)


def test_status_post_then_read_back_then_appears_in_own_timeline(
    blog_client: TimedMastodonClient,
) -> None:
    """The core stateful guarantee: post -> the post is visible on later reads."""
    me = blog_client.account_verify_credentials()
    unique = "integration smoke post 1f2e3d"

    posted = blog_client.status_post(unique)
    assert posted.id

    # 1. Direct re-fetch by id round-trips the content.
    refetched = blog_client.status(posted.id)
    assert refetched.id == posted.id
    assert unique in refetched.content

    # 2. It shows up in the author's own account_statuses (stateful read-back).
    mine = blog_client.account_statuses(me.id, limit=40)
    assert posted.id in {s.id for s in mine}


def test_missing_status_raises_not_found(blog_client: TimedMastodonClient) -> None:
    with pytest.raises(MastodonNotFoundError):
        blog_client.status("0")
