"""
DuckDB analytics benchmarks against the big perf database.

The forum tab is the historically worst-performing surface, so it gets the
most coverage here: the raw ``forum_thread_summaries`` aggregation (cold
cache), the warm-cache path, and the full ``/api/forum/threads`` endpoint
(following-accounts fetch + DuckDB scan + Python faceting/sorting) exactly as
a request executes it.

Works on the sqlite and postgres backends (DuckDB attaches either via its
official extensions); skips on turso, which duck.py does not support.
"""

from __future__ import annotations

import pytest

from mastodon_is_my_blog.db_backend import DatabaseBackend, resolve_backend

from test_perf.conftest import requires_perf_db

pytestmark = [
    requires_perf_db,
    pytest.mark.perf_db,
    pytest.mark.benchmark(min_rounds=5, warmup=False, disable_gc=True),
    pytest.mark.skipif(
        resolve_backend() == DatabaseBackend.TURSO,
        reason="DuckDB analytics are disabled on the turso backend",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def ready(perf_db_ready):
    return perf_db_ready


@pytest.fixture(scope="module")
def meta_obj(loop, perf_ids):
    """The MetaAccount row, needed to call route functions directly."""
    from sqlalchemy import select

    from mastodon_is_my_blog.store import MetaAccount, async_session

    meta_id, _ = perf_ids

    async def fetch():
        async with async_session() as session:
            return (await session.execute(select(MetaAccount).where(MetaAccount.id == meta_id))).scalar_one()

    return loop.run_until_complete(fetch())


# --- Forum (the known worst offender) ---------------------------------------


def test_forum_thread_summaries_cold(abench, perf_ids):
    """The heavy DuckDB CTE, with the 30s result cache defeated every round."""
    from mastodon_is_my_blog import duck

    meta_id, identity_id = perf_ids

    async def cold():
        duck.FORUM_SUMMARY_CACHE.clear()
        return await duck.forum_thread_summaries(meta_id, identity_id, False, set())

    threads = abench(cold)
    assert threads, "seeded DB should produce forum threads (roots with >=2 participants)"


def test_forum_thread_summaries_warm(abench, perf_ids, loop):
    """Cache-hit path — should be near-instant; a regression here means the cache broke."""
    from mastodon_is_my_blog import duck

    meta_id, identity_id = perf_ids
    duck.FORUM_SUMMARY_CACHE.clear()
    loop.run_until_complete(duck.forum_thread_summaries(meta_id, identity_id, False, set()))

    threads = abench(duck.forum_thread_summaries, meta_id, identity_id, False, set())
    assert threads


def test_forum_endpoint_recent(abench, perf_ids, meta_obj):
    """Full /api/forum/threads request path: SQL + DuckDB + faceting + pagination."""
    from mastodon_is_my_blog import duck
    from mastodon_is_my_blog.routes.forum import get_forum_threads

    _, identity_id = perf_ids

    async def endpoint():
        duck.FORUM_SUMMARY_CACHE.clear()
        return await get_forum_threads(
            identity_id=identity_id,
            top_filter="recent",
            hashtag=[],
            uncommon_word=[],
            root_instance=[],
            limit=25,
            before=None,
            include_content_hub=False,
            meta=meta_obj,
        )

    result = abench(endpoint)
    assert result["items"]


def test_forum_friend_reply_counts(abench, perf_ids, loop):
    from mastodon_is_my_blog import duck

    meta_id, identity_id = perf_ids
    duck.FORUM_SUMMARY_CACHE.clear()
    threads = loop.run_until_complete(duck.forum_thread_summaries(meta_id, identity_id, False, set()))
    root_ids = [t["root_id"] for t in threads[:100]]
    following = {t["author_acct"] for t in threads[:200]}

    counts = abench(duck.forum_friend_reply_counts, meta_id, identity_id, root_ids, following)
    assert isinstance(counts, dict)


# --- Other analytics surfaces -------------------------------------------------


def test_hashtag_trends(abench, perf_ids):
    from mastodon_is_my_blog import duck

    meta_id, identity_id = perf_ids
    rows = abench(duck.hashtag_trends, meta_id, identity_id, "week", 20)
    assert rows


def test_hashtag_counts(abench, perf_ids):
    from mastodon_is_my_blog import duck

    meta_id, identity_id = perf_ids
    rows = abench(duck.hashtag_counts, meta_id, identity_id)
    assert rows


def test_posting_heatmap(abench, perf_ids):
    from mastodon_is_my_blog import duck

    meta_id, identity_id = perf_ids
    rows = abench(duck.posting_heatmap, meta_id, identity_id)
    assert rows


def test_activity_calendar(abench, perf_ids):
    from mastodon_is_my_blog import duck

    meta_id, identity_id = perf_ids
    rows = abench(duck.activity_calendar, meta_id, identity_id)
    assert rows


def test_top_reposters(abench, perf_ids):
    from mastodon_is_my_blog import duck

    meta_id, identity_id = perf_ids
    rows = abench(duck.top_reposters, meta_id, identity_id, 30, 50)
    assert rows


def test_notification_trends(abench, perf_ids):
    from mastodon_is_my_blog import duck

    meta_id, identity_id = perf_ids
    result = abench(duck.notification_trends, meta_id, identity_id)
    assert result


def test_content_regex_search(abench, perf_ids):
    """Full content scan — inherently table-scan shaped; watch it, don't panic over it."""
    from mastodon_is_my_blog import duck

    meta_id, identity_id = perf_ids
    rows = abench(duck.content_regex_search, meta_id, identity_id, "sourdough", 100)
    assert isinstance(rows, list)
