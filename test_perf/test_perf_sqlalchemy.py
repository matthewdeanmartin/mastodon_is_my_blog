"""
SQLAlchemy hot-path benchmarks against the big perf database.

Covers the read queries behind the main feed (first page, deep cursor page,
per-author page), the counts panel, the unread badge, and the write path
(bulk_upsert_posts). Run via `make perf-baseline-sqlite` / `perf-check-sqlite`
(or the postgres variants) — see rtd/reference/ensuring_mimb_stays_fast.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import and_, func, select

from test_perf.conftest import requires_perf_db

pytestmark = [
    requires_perf_db,
    pytest.mark.perf_db,
    pytest.mark.benchmark(min_rounds=5, warmup=False, disable_gc=True),
]

PAGE_SIZE = 50


@pytest.fixture(scope="module", autouse=True)
def ready(perf_db_ready):
    return perf_db_ready


def feed_page_stmt(meta_id: int, identity_id: int, before: datetime | None = None, author: str | None = None):
    from mastodon_is_my_blog.store import CachedPost, SeenPost

    stmt = (
        select(CachedPost, SeenPost.post_id.label("is_seen"))
        .outerjoin(
            SeenPost,
            and_(SeenPost.post_id == CachedPost.id, SeenPost.meta_account_id == meta_id),
        )
        .where(
            CachedPost.meta_account_id == meta_id,
            CachedPost.fetched_by_identity_id == identity_id,
            CachedPost.content_hub_only.is_(False),
        )
        .order_by(CachedPost.created_at.desc(), CachedPost.id.desc())
        .limit(PAGE_SIZE)
    )
    if before is not None:
        stmt = stmt.where(CachedPost.created_at < before)
    if author is not None:
        stmt = stmt.where(func.coalesce(CachedPost.actor_acct, CachedPost.author_acct) == author)
    return stmt


async def run_stmt(stmt) -> list:
    from mastodon_is_my_blog.store import async_session

    async with async_session() as session:
        return (await session.execute(stmt)).all()


def test_feed_first_page(abench, perf_ids):
    meta_id, identity_id = perf_ids
    rows = abench(run_stmt, feed_page_stmt(meta_id, identity_id))
    assert len(rows) == PAGE_SIZE


def test_feed_deep_page(abench, perf_ids):
    """Cursor pagination six months back — exercises the created_at index mid-history."""
    meta_id, identity_id = perf_ids
    before = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=180)
    rows = abench(run_stmt, feed_page_stmt(meta_id, identity_id, before=before))
    assert rows


def test_feed_author_page(abench, perf_ids, loop):
    """Per-author feed — the profile view query shape."""
    from mastodon_is_my_blog.store import CachedPost

    meta_id, identity_id = perf_ids

    async def busiest_author() -> str:
        stmt = select(CachedPost.author_acct, func.count().label("n")).where(CachedPost.meta_account_id == meta_id, CachedPost.fetched_by_identity_id == identity_id).group_by(CachedPost.author_acct).order_by(func.count().desc()).limit(1)
        return (await run_stmt(stmt))[0][0]

    author = loop.run_until_complete(busiest_author())
    rows = abench(run_stmt, feed_page_stmt(meta_id, identity_id, author=author))
    assert rows


def test_counts_panel(abench, perf_ids):
    """get_counts_optimized — the giant conditional-aggregation select behind the sidebar."""
    from mastodon_is_my_blog.queries import get_counts_optimized
    from mastodon_is_my_blog.store import async_session

    meta_id, identity_id = perf_ids

    async def counts() -> dict:
        async with async_session() as session:
            return await get_counts_optimized(session, meta_id, identity_id)

    result = abench(counts)
    assert result


def test_unread_count(abench, perf_ids):
    from mastodon_is_my_blog.store import CachedPost, SeenPost

    meta_id, identity_id = perf_ids
    stmt = (
        select(func.count(CachedPost.id))
        .outerjoin(
            SeenPost,
            and_(SeenPost.post_id == CachedPost.id, SeenPost.meta_account_id == meta_id),
        )
        .where(
            CachedPost.meta_account_id == meta_id,
            CachedPost.fetched_by_identity_id == identity_id,
            SeenPost.post_id.is_(None),
        )
    )
    rows = abench(run_stmt, stmt)
    assert rows[0][0] > 0


def test_bulk_upsert_posts_batch(abench, perf_ids):
    """Ingest throughput: upsert a 500-status batch (rolled back each round)."""
    from mastodon_is_my_blog.queries import bulk_upsert_posts
    from mastodon_is_my_blog.store import async_session

    meta_id, identity_id = perf_ids

    def make_statuses(n: int) -> list[dict]:
        base = datetime(2030, 1, 1)
        return [
            {
                "id": uuid.uuid4().hex,
                "reblog": None,
                "content": "<p>perf ingest batch post with a plausible amount of text in it</p>" * 3,
                "created_at": base + timedelta(seconds=i),
                "visibility": "public",
                "account": {"id": f"ingest-{i % 40}", "acct": f"ingest{i % 40}@perf.example"},
                "in_reply_to_id": None,
                "in_reply_to_account_id": None,
                "media_attachments": [],
                "tags": [{"name": "perftag"}],
                "replies_count": 0,
                "reblogs_count": 0,
                "favourites_count": 0,
            }
            for i in range(n)
        ]

    async def ingest() -> tuple[int, int]:
        statuses = make_statuses(500)
        async with async_session() as session:
            result = await bulk_upsert_posts(session, meta_id, identity_id, statuses)
            await session.rollback()
            return result

    new_count, _updated = abench(ingest)
    assert new_count == 500
