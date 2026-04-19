"""
Smoke tests for the DuckDB analytics layer.

The critical invariant: a row committed through SQLAlchemy must be visible
to DuckDB via ``sqlite_scanner`` within the same request. If WAL isolation
were to hide the commit, all of our analytical endpoints would return
stale data silently.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mastodon_is_my_blog import duck
from mastodon_is_my_blog.store import (
    Base,
    CachedNotification,
    CachedPost,
    MastodonIdentity,
    MetaAccount,
)


@pytest.fixture
def sqlite_file(tmp_path: Path, monkeypatch) -> Path:
    """Create an empty SQLite file and point the app's path helper at it."""
    db_path = tmp_path / "duck_smoke.db"
    # Make sure the file exists with schema before DuckDB tries to attach.
    monkeypatch.setattr(
        "mastodon_is_my_blog.db_path.get_sqlite_file_path",
        lambda: str(db_path),
    )
    # ``duck`` imports the symbol by name, so patch there too.
    monkeypatch.setattr(
        "mastodon_is_my_blog.duck.get_sqlite_file_path",
        lambda: str(db_path),
    )
    return db_path


@pytest_asyncio.fixture
async def seeded_engine(sqlite_file: Path):
    """Return an async SQLAlchemy engine pointed at sqlite_file with schema created."""
    url = f"sqlite+aiosqlite:///{sqlite_file}"
    engine = create_async_engine(url, echo=False)

    async with engine.begin() as conn:
        # WAL matches the production PRAGMA so the test exercises real isolation.
        from sqlalchemy import text as sa_text

        await conn.execute(sa_text("PRAGMA journal_mode=WAL"))
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def duck_connection(sqlite_file, seeded_engine):
    """Ensure the DuckDB sqlite extension is installed for the test."""
    duck.startup()
    yield
    duck.shutdown()


@pytest.mark.asyncio
async def test_commit_visible_to_duckdb(seeded_engine, duck_connection) -> None:
    factory = async_sessionmaker(seeded_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(MetaAccount(id=1, username="default"))
        session.add(
            MastodonIdentity(
                id=1,
                meta_account_id=1,
                config_name="main",
                api_base_url="https://example.social",
                client_id="c",
                client_secret="s",
                access_token="t",
                acct="me@example.social",
                account_id="99",
            )
        )
        session.add(
            CachedPost(
                id="post-1",
                meta_account_id=1,
                fetched_by_identity_id=1,
                content="<p>hello world</p>",
                created_at=datetime(2026, 4, 10, 14, 30, tzinfo=timezone.utc),
                visibility="public",
                author_acct="me@example.social",
                author_id="99",
                tags=json.dumps(["Test"]),
            )
        )
        await session.commit()

    rows = await duck.run(
        f"SELECT id, author_acct FROM {duck.ATTACH_ALIAS}.cached_posts",
    )
    assert rows == [("post-1", "me@example.social")]


@pytest.mark.asyncio
async def test_hashtag_trends_aggregates_json_tags(
    seeded_engine, duck_connection
) -> None:
    factory = async_sessionmaker(seeded_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(MetaAccount(id=1, username="default"))
        session.add(
            MastodonIdentity(
                id=1,
                meta_account_id=1,
                config_name="main",
                api_base_url="https://example.social",
                client_id="c",
                client_secret="s",
                access_token="t",
                acct="me@example.social",
                account_id="99",
            )
        )
        for n in range(3):
            session.add(
                CachedPost(
                    id=f"post-a{n}",
                    meta_account_id=1,
                    fetched_by_identity_id=1,
                    content="x",
                    created_at=datetime(2026, 4, 10, tzinfo=timezone.utc),
                    visibility="public",
                    author_acct="me@example.social",
                    author_id="99",
                    tags=json.dumps(["python", "sqlite"]),
                )
            )
        session.add(
            CachedPost(
                id="post-b",
                meta_account_id=1,
                fetched_by_identity_id=1,
                content="x",
                created_at=datetime(2026, 4, 10, tzinfo=timezone.utc),
                visibility="public",
                author_acct="me@example.social",
                author_id="99",
                tags=json.dumps(["python"]),
            )
        )
        await session.commit()

    rows = await duck.hashtag_trends(meta_id=1, identity_id=1, bucket="week", top=5)
    by_tag = {r["tag"]: r["count"] for r in rows}
    assert by_tag == {"python": 4, "sqlite": 3}


@pytest.mark.asyncio
async def test_posting_heatmap_groups_by_hour_and_dow(
    seeded_engine, duck_connection
) -> None:
    factory = async_sessionmaker(seeded_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(MetaAccount(id=1, username="default"))
        session.add(
            MastodonIdentity(
                id=1,
                meta_account_id=1,
                config_name="main",
                api_base_url="https://example.social",
                client_id="c",
                client_secret="s",
                access_token="t",
                acct="me@example.social",
                account_id="99",
            )
        )
        # 2026-04-13 is a Monday. date_part('dow', ...) returns 1 for Monday.
        for hour in (9, 9, 14):
            session.add(
                CachedPost(
                    id=f"post-{hour}-{len(session.new)}",
                    meta_account_id=1,
                    fetched_by_identity_id=1,
                    content="x",
                    created_at=datetime(2026, 4, 13, hour, 0, tzinfo=timezone.utc),
                    visibility="public",
                    author_acct="me@example.social",
                    author_id="99",
                    tags="[]",
                )
            )
        await session.commit()

    rows = await duck.posting_heatmap(meta_id=1, identity_id=1)
    cells = {(r["dow"], r["hour"]): r["count"] for r in rows}
    assert cells == {(1, 9): 2, (1, 14): 1}


@pytest.mark.asyncio
async def test_content_regex_search_case_insensitive(
    seeded_engine, duck_connection
) -> None:
    factory = async_sessionmaker(seeded_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(MetaAccount(id=1, username="default"))
        session.add(
            MastodonIdentity(
                id=1,
                meta_account_id=1,
                config_name="main",
                api_base_url="https://example.social",
                client_id="c",
                client_secret="s",
                access_token="t",
                acct="me@example.social",
                account_id="99",
            )
        )
        session.add(
            CachedPost(
                id="hit",
                meta_account_id=1,
                fetched_by_identity_id=1,
                content="<p>DuckDB is fast</p>",
                created_at=datetime(2026, 4, 10, tzinfo=timezone.utc),
                visibility="public",
                author_acct="me@example.social",
                author_id="99",
                tags="[]",
            )
        )
        session.add(
            CachedPost(
                id="miss",
                meta_account_id=1,
                fetched_by_identity_id=1,
                content="<p>nothing here</p>",
                created_at=datetime(2026, 4, 10, tzinfo=timezone.utc),
                visibility="public",
                author_acct="me@example.social",
                author_id="99",
                tags="[]",
            )
        )
        await session.commit()

    rows = await duck.content_regex_search(meta_id=1, identity_id=1, pattern="duckdb")
    assert [r["id"] for r in rows] == ["hit"]


@pytest.mark.asyncio
async def test_top_reposters_splits_current_and_prior(
    seeded_engine, duck_connection
) -> None:
    now = datetime.now(timezone.utc)
    factory = async_sessionmaker(seeded_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(MetaAccount(id=1, username="default"))
        session.add(
            MastodonIdentity(
                id=1,
                meta_account_id=1,
                config_name="main",
                api_base_url="https://example.social",
                client_id="c",
                client_secret="s",
                access_token="t",
                acct="me@example.social",
                account_id="99",
            )
        )
        # Two current-window reblogs from alice, one prior-window from alice,
        # plus one current-window reblog from bob.
        for i, (acct, delta_days) in enumerate(
            [("alice", 1), ("alice", 5), ("alice", 40), ("bob", 2)]
        ):
            session.add(
                CachedNotification(
                    id=f"n-{i}",
                    meta_account_id=1,
                    identity_id=1,
                    type="reblog",
                    created_at=now - timedelta(days=delta_days),
                    account_id=f"acc-{acct}",
                    account_acct=acct,
                    status_id=None,
                )
            )
        # Non-reblog should be ignored.
        session.add(
            CachedNotification(
                id="n-fav",
                meta_account_id=1,
                identity_id=1,
                type="favourite",
                created_at=now - timedelta(days=1),
                account_id="acc-alice",
                account_acct="alice",
                status_id=None,
            )
        )
        await session.commit()

    rows = await duck.top_reposters(meta_id=1, identity_id=1, window_days=30, limit=10)
    by_actor = {r["account_acct"]: r for r in rows}
    assert by_actor["alice"]["current"] == 2
    assert by_actor["alice"]["prior"] == 1
    assert by_actor["alice"]["delta"] == 1
    assert by_actor["bob"]["current"] == 1
    assert by_actor["bob"]["prior"] == 0
