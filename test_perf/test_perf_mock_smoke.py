"""
Fast perf smoke tests — safe for CI, no big database required.

These exercise the real ingest and read paths (mastodon_mock over HTTP →
deep_fetch_user_timeline → bulk_upsert_posts → feed query) against an
in-memory sqlite DB, and assert *generous* wall-clock budgets: roughly 10x
what the paths take on a slow CI runner. They exist to catch accidental
O(n²) loops, per-row commits, N+1 queries and similar order-of-magnitude
regressions — a 5–10% slowdown will never fail them. Real numbers come from
the big-DB benchmarks (see rtd/reference/ensuring_mimb_stays_fast.md).

Self-skips on Python < 3.13 or when mastodon_mock[test] is not installed,
mirroring test_integration/.
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest

if sys.version_info < (3, 13):
    pytest.skip("mastodon_mock requires Python >= 3.13", allow_module_level=True)

pytest.importorskip("mastodon_mock", reason="install mastodon_mock[test] to run the perf smoke suite")

from mastodon import Mastodon  # noqa: E402
from mastodon_mock.config import SeedAccount, SeedConfig, SeedFollow, SeedStatus  # noqa: E402
from mastodon_mock.testing import MockServer  # noqa: E402
from sqlalchemy import and_, func, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from mastodon_is_my_blog.catchup import deep_fetch_user_timeline  # noqa: E402
from mastodon_is_my_blog.queries import bulk_upsert_posts  # noqa: E402
from mastodon_is_my_blog.store import Base, CachedPost, SeenPost  # noqa: E402

pytestmark = pytest.mark.perf_smoke

ALICE_TOKEN = "alice_token"
SEEDED_STATUSES = 120

# Wall-clock budgets, deliberately ~10x a slow CI runner's typical time.
FETCH_AND_INGEST_BUDGET_S = 30.0
BULK_UPSERT_1000_BUDGET_S = 10.0
FEED_QUERY_BUDGET_S = 2.0

META_ID = 1
IDENTITY_ID = 1


@pytest.fixture(scope="module")
def mock_server_url() -> Iterator[str]:
    seed = SeedConfig(
        accounts=[
            SeedAccount(username="alice", display_name="Alice", access_token=ALICE_TOKEN),
            SeedAccount(username="bob", display_name="Bob", access_token="bob_token"),
        ],
        follows=[SeedFollow(follower="alice", following="bob")],
        statuses=[SeedStatus(account="bob", text=f"perf smoke seed status number {i} with a bit of extra text") for i in range(SEEDED_STATUSES)],
    )
    with MockServer(seed=seed) as server:
        yield server.base_url


@pytest.fixture
def loop() -> Iterator[asyncio.AbstractEventLoop]:
    new_loop = asyncio.new_event_loop()
    yield new_loop
    new_loop.close()


@pytest.fixture
def memory_db(loop):
    """(engine, session_factory) on in-memory sqlite with the app schema."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    loop.run_until_complete(setup())
    yield engine, async_sessionmaker(engine, expire_on_commit=False)
    loop.run_until_complete(engine.dispose())


def make_statuses(n: int) -> list[dict]:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "id": uuid.uuid4().hex,
            "reblog": None,
            "content": "<p>perf smoke post with a plausible amount of text in the body</p>" * 3,
            "created_at": base + timedelta(seconds=i),
            "visibility": "public",
            "account": {"id": f"a{i % 25}", "acct": f"user{i % 25}@perf.example"},
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


def test_fetch_and_ingest_timeline_within_budget(mock_server_url, memory_db, loop):
    """End-to-end ingest: paginate 120 statuses over HTTP and upsert them."""
    _, factory = memory_db
    client = Mastodon(access_token=ALICE_TOKEN, api_base_url=mock_server_url)
    me = client.account_verify_credentials()
    home = client.timeline_home(limit=40)
    bob_id = next(s.account.id for s in home if s.account.acct == "bob")
    assert str(bob_id) != str(me.id)

    async def fetch_and_ingest() -> int:
        total = 0
        async with factory() as session:
            async for page in deep_fetch_user_timeline(client, bob_id, inter_page_delay=0):
                new, updated = await bulk_upsert_posts(session, META_ID, IDENTITY_ID, page)
                total += new + updated
            await session.commit()
        return total

    start = time.perf_counter()
    total = loop.run_until_complete(fetch_and_ingest())
    elapsed = time.perf_counter() - start

    assert total >= SEEDED_STATUSES
    assert elapsed < FETCH_AND_INGEST_BUDGET_S, f"fetch+ingest of {total} statuses took {elapsed:.1f}s (budget {FETCH_AND_INGEST_BUDGET_S}s) — order-of-magnitude regression in the ingest path"


def test_bulk_upsert_1000_within_budget(memory_db, loop):
    _, factory = memory_db
    statuses = make_statuses(1000)

    async def ingest() -> int:
        async with factory() as session:
            new, _ = await bulk_upsert_posts(session, META_ID, IDENTITY_ID, statuses)
            await session.commit()
        return new

    start = time.perf_counter()
    new = loop.run_until_complete(ingest())
    elapsed = time.perf_counter() - start

    assert new == 1000
    assert elapsed < BULK_UPSERT_1000_BUDGET_S, f"bulk_upsert_posts of 1000 statuses took {elapsed:.1f}s (budget {BULK_UPSERT_1000_BUDGET_S}s)"


def test_feed_query_within_budget(memory_db, loop):
    """First feed page over a few thousand rows — catches a broken query plan, not noise."""
    _, factory = memory_db

    async def seed_and_query() -> tuple[float, int]:
        async with factory() as session:
            for _ in range(3):
                await bulk_upsert_posts(session, META_ID, IDENTITY_ID, make_statuses(1000))
            await session.commit()

        start = time.perf_counter()
        async with factory() as session:
            stmt = (
                select(CachedPost, SeenPost.post_id)
                .outerjoin(SeenPost, and_(SeenPost.post_id == CachedPost.id, SeenPost.meta_account_id == META_ID))
                .where(
                    CachedPost.meta_account_id == META_ID,
                    CachedPost.fetched_by_identity_id == IDENTITY_ID,
                    CachedPost.content_hub_only.is_(False),
                )
                .order_by(CachedPost.created_at.desc(), CachedPost.id.desc())
                .limit(50)
            )
            rows = (await session.execute(stmt)).all()
            count = (await session.execute(select(func.count()).select_from(CachedPost))).scalar_one()
        return time.perf_counter() - start, len(rows) and count

    elapsed, count = loop.run_until_complete(seed_and_query())
    assert count == 3000
    assert elapsed < FEED_QUERY_BUDGET_S, f"feed page over {count} rows took {elapsed:.2f}s (budget {FEED_QUERY_BUDGET_S}s)"
