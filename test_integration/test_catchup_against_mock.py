"""Exercise the blog's catchup logic against the stateful mock.

``catchup.deep_fetch_user_timeline`` is the blog's real paginated fetch loop: it
walks ``account_statuses`` pages by ``max_id`` until the instance runs out of
history. Running it against the mock proves two things at once:

* the blog's pagination/stop logic works against a server that implements the
  ``max_id`` + Link-header contract the way real Mastodon does, and
* the mock is stateful — statuses we post show up in the very next deep fetch.
"""

from __future__ import annotations

import pytest
from mastodon import Mastodon

from mastodon_is_my_blog.catchup import deep_fetch_user_timeline


async def _collect_pages(*args, **kwargs) -> list[list[dict]]:
    """Drain the async-generator deep fetch into a list of pages."""
    pages: list[list[dict]] = []
    async for page in deep_fetch_user_timeline(*args, **kwargs):
        pages.append(page)
    return pages


@pytest.mark.asyncio
async def test_deep_fetch_reads_seeded_history(raw_client: Mastodon) -> None:
    """Bob has seeded statuses; deep fetch should surface them in one short page."""
    me = raw_client.account_verify_credentials()
    home = raw_client.timeline_home(limit=40)
    bob_accounts = {s.account.id for s in home if s.account.acct == "bob"}
    assert bob_accounts, "bob should appear in alice's home timeline"
    bob_id = bob_accounts.pop()
    assert str(bob_id) != str(me.id)

    pages = await _collect_pages(raw_client, bob_id, inter_page_delay=0)

    all_ids = {str(s["id"]) for page in pages for s in page}
    assert all_ids, "deep fetch should return the seeded statuses"
    # Bob only ever has the two seeded statuses (no test posts as bob), which fit
    # well under the 40-per-page cap → exactly one page.
    assert len(pages) == 1


@pytest.mark.asyncio
async def test_posts_are_immediately_visible_to_deep_fetch(
    raw_client: Mastodon,
) -> None:
    """Post as the authenticated account, then deep-fetch its own timeline.

    This is the end-to-end stateful proof through the blog's own fetch loop:
    what we write is what the next read sees.
    """
    me = raw_client.account_verify_credentials()

    markers = [f"deep-fetch round-trip post {i}" for i in range(3)]
    posted_ids = {raw_client.status_post(text).id for text in markers}

    pages = await _collect_pages(raw_client, me.id, inter_page_delay=0)
    fetched_ids = {s["id"] for page in pages for s in page}

    assert posted_ids <= fetched_ids


@pytest.mark.asyncio
async def test_deep_fetch_honours_stop_at_id(raw_client: Mastodon) -> None:
    """stop_at_id should prevent re-walking history the blog already cached."""
    me = raw_client.account_verify_credentials()

    first = raw_client.status_post("stop-at-id baseline post")
    # Everything <= this id is considered "already cached" by the blog.
    stop_at = first.id

    later = raw_client.status_post("stop-at-id newer post")

    pages = await _collect_pages(
        raw_client, me.id, stop_at_id=stop_at, inter_page_delay=0
    )
    fetched_ids = {str(s["id"]) for page in pages for s in page}

    # The newer post is past the stop marker and must be fetched...
    assert str(later.id) in fetched_ids
    # ...and the loop stopped, so the run is bounded (no infinite paging).
    assert len(pages) <= 2
