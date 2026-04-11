from collections.abc import Sequence

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from mastodon_is_my_blog.store import (
    CachedNotification,
    CachedPost,
    MastodonIdentity,
    MetaAccount,
    async_session,
    engine,
)

EXPECTED_TABLES = {
    "alembic_version",
    "app_state",
    "cached_accounts",
    "cached_notifications",
    "cached_posts",
    "mastodon_identities",
    "meta_accounts",
    "seen_posts",
    "tokens",
}

COUNTED_TABLES = (
    "meta_accounts",
    "mastodon_identities",
    "cached_posts",
    "cached_notifications",
    "seen_posts",
    "tokens",
)

EXPECTED_CACHED_POST_INDEXES = {
    "ix_cached_posts_author_acct",
    "ix_cached_posts_author_id",
    "ix_posts_in_reply_to",
    "ix_posts_meta_author",
    "ix_posts_meta_clean",
    "ix_posts_meta_created",
    "ix_posts_meta_identity_author",
    "ix_posts_meta_identity_created",
}


@pytest_asyncio.fixture(scope="module", autouse=True)
async def dispose_db_engine_after_tests():
    yield
    await engine.dispose()


async def fetch_scalar_list(query: str) -> Sequence[str]:
    async with async_session() as session:
        result = await session.execute(text(query))
        return result.scalars().all()


@pytest.mark.asyncio
async def test_real_db_exposes_expected_tables() -> None:
    table_names = await fetch_scalar_list(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )

    assert EXPECTED_TABLES.issubset(set(table_names))


@pytest.mark.asyncio
@pytest.mark.parametrize("table_name", COUNTED_TABLES)
async def test_real_db_table_counts_are_non_negative(table_name: str) -> None:
    async with async_session() as session:
        result = await session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
        count = result.scalar_one()

    assert isinstance(count, int)
    assert count >= 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "primary_key_attr"),
    [
        (MetaAccount, "id"),
        (MastodonIdentity, "id"),
        (CachedPost, "id"),
        (CachedNotification, "id"),
    ],
)
async def test_real_db_orm_queries_can_read_optional_sample_rows(
    model: type, primary_key_attr: str
) -> None:
    async with async_session() as session:
        result = await session.execute(select(model).limit(1))
        row = result.scalar_one_or_none()

    if row is not None:
        assert isinstance(getattr(row, primary_key_attr), str | int)


@pytest.mark.asyncio
async def test_real_db_cached_posts_has_expected_indexes() -> None:
    index_names = await fetch_scalar_list(
        "SELECT name FROM sqlite_master "
        "WHERE type='index' AND tbl_name='cached_posts' ORDER BY name"
    )

    assert EXPECTED_CACHED_POST_INDEXES.issubset(set(index_names))


@pytest.mark.asyncio
async def test_real_db_cached_posts_has_expected_columns() -> None:
    async with async_session() as session:
        result = await session.execute(text("PRAGMA table_info(cached_posts)"))
        column_names = {row[1] for row in result.fetchall()}

    assert {
        "id",
        "meta_account_id",
        "fetched_by_identity_id",
        "content",
        "created_at",
        "author_acct",
        "is_reblog",
        "is_reply",
        "has_media",
        "has_video",
        "has_news",
        "has_tech",
        "has_link",
        "has_question",
    }.issubset(column_names)
