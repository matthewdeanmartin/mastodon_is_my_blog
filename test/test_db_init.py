"""Phase 2 of the Turso/Postgres plan (spec/turso_support_phases.md).

Fresh-DB Alembic stamping + schema-version reporting. The historical migration
chain is incremental (create_all already builds every index), so a fresh DB is
create_all'd then *stamped* at head, not upgraded from empty.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from mastodon_is_my_blog import db_init, schema_version
from mastodon_is_my_blog.store import Base


@pytest_asyncio.fixture
async def fresh_engine(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'fresh.db').as_posix()}"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_fresh_db_starts_unstamped(fresh_engine):
    assert await db_init.current_revision(fresh_engine) is None


@pytest.mark.asyncio
async def test_ensure_schema_stamped_sets_head(fresh_engine):
    rev = await db_init.ensure_schema_stamped(fresh_engine)
    assert rev is not None
    assert await db_init.current_revision(fresh_engine) == rev


@pytest.mark.asyncio
async def test_ensure_schema_stamped_is_idempotent(fresh_engine):
    first = await db_init.ensure_schema_stamped(fresh_engine)
    second = await db_init.ensure_schema_stamped(fresh_engine)
    assert first == second


@pytest.mark.asyncio
async def test_stamped_head_is_latest_migration(fresh_engine):
    rev = await db_init.ensure_schema_stamped(fresh_engine)
    # 016 is the head added in Phase 2; keep this assertion loose but meaningful.
    assert rev == "016"


@pytest.mark.asyncio
async def test_schema_version_reads_stamp(fresh_engine):
    assert await schema_version.get_schema_version(fresh_engine) is None
    rev = await db_init.ensure_schema_stamped(fresh_engine)
    assert await schema_version.get_schema_version(fresh_engine) == rev


def test_redact_hides_password_and_token():
    assert "secret" not in schema_version._redact("postgresql+asyncpg://user:secret@host/db")
    assert "abc123" not in schema_version._redact("sqlite+libsql://db.turso.io?authToken=abc123")
