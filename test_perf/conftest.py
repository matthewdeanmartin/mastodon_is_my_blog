"""
Fixtures for the performance suites (see rtd/reference/ensuring_mimb_stays_fast.md).

Two families of tests live in test_perf/:

* Big-DB benchmarks (test_perf_sqlalchemy.py, test_perf_duckdb.py) — run
  against a realistic ~1 GB database seeded by seed_perf_db.py. Opt-in via
  MIMB_PERF=1 plus the usual backend env (DB_URL / DB_BACKEND +
  APP_POSTGRES_URL). Never run in CI; run at release time via the Makefile
  perf-* targets.

* Mock smoke tests (test_perf_mock_smoke.py) — short, budget-based checks
  against mastodon_mock and an in-memory sqlite DB. Safe for CI; they only
  fail on order-of-magnitude regressions, never on 5–10% noise.

Benchmarks are synchronous tests driving coroutines on one shared event loop,
because the app engine's pooled connections are bound to the loop they were
created on — a fresh loop per iteration (asyncio.run) would poison the pool.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Iterator
from typing import Any

import pytest

PERF_ENABLED = os.environ.get("MIMB_PERF") == "1"

requires_perf_db = pytest.mark.skipif(
    not PERF_ENABLED,
    reason="big-DB perf benchmarks are opt-in: set MIMB_PERF=1 and point DB_URL at a seeded perf database (make perf-seed)",
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "perf_db: benchmark against the big local perf database (opt-in via MIMB_PERF=1)")
    config.addinivalue_line("markers", "perf_smoke: fast budget-based perf check, safe for CI")


@pytest.fixture(scope="session")
def loop() -> Iterator[asyncio.AbstractEventLoop]:
    """One event loop for the whole session so engine pools stay valid."""
    new_loop = asyncio.new_event_loop()
    yield new_loop
    if PERF_ENABLED:
        from mastodon_is_my_blog.store import engine

        new_loop.run_until_complete(engine.dispose())
    new_loop.close()


@pytest.fixture(scope="session")
def perf_ids() -> tuple[int, int]:
    """(meta_account_id, identity_id) to benchmark against; seeded DBs use 1/1."""
    return (
        int(os.environ.get("MIMB_PERF_META_ID", "1")),
        int(os.environ.get("MIMB_PERF_IDENTITY_ID", "1")),
    )


@pytest.fixture(scope="session")
def perf_db_ready(loop: asyncio.AbstractEventLoop, perf_ids: tuple[int, int]) -> int:
    """Sanity-check the target DB before burning benchmark time; returns post count."""
    from sqlalchemy import func, select

    from mastodon_is_my_blog.store import CachedPost, async_session, engine

    meta_id, identity_id = perf_ids

    async def count_posts() -> int:
        async with async_session() as session:
            return (await session.execute(select(func.count()).select_from(CachedPost).where(CachedPost.meta_account_id == meta_id, CachedPost.fetched_by_identity_id == identity_id))).scalar_one()

    n = loop.run_until_complete(count_posts())
    if n < 10_000:
        pytest.exit(
            f"Perf DB at {engine.url.render_as_string(hide_password=True)} has only {n:,} posts for meta={meta_id}/identity={identity_id}. Seed it first: make perf-seed (or perf-seed-postgres).",
            returncode=3,
        )
    return n


@pytest.fixture
def abench(benchmark: Any, loop: asyncio.AbstractEventLoop) -> Callable:
    """Benchmark an async callable: abench(coro_fn, *args, **kwargs)."""

    def run(coro_fn: Callable, *args: Any, **kwargs: Any) -> Any:
        return benchmark(lambda: loop.run_until_complete(coro_fn(*args, **kwargs)))

    return run
