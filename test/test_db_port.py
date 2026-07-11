"""Phase 3 of the Turso/Postgres plan (spec/turso_support_phases.md).

Export/import/port/diff/verify across backends. Exercised on sqlite files (the
JSONL path and the SQLAlchemy Core statements are backend-agnostic).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mastodon_is_my_blog import db_port
from mastodon_is_my_blog.store import (
    Base,
    CachedPost,
    MastodonIdentity,
    MetaAccount,
)


def _url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


async def _create_schema(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


async def _seed(url: str, *, post_content: str = "<p>hi</p>") -> None:
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(MetaAccount(id=1, username="default", created_at=datetime(2026, 7, 8, 12, 0)))
        session.add(
            MastodonIdentity(
                id=1,
                meta_account_id=1,
                api_base_url="https://x.social",
                client_id="cid",
                client_secret="sec",
                access_token="tok",
                acct="me@x.social",
                account_id="9",
            )
        )
        session.add(
            CachedPost(
                id="p1",
                meta_account_id=1,
                fetched_by_identity_id=1,
                content=post_content,
                created_at=datetime(2026, 7, 8, 12, 1),
                visibility="public",
                author_acct="me@x.social",
                author_id="9",
                actor_acct="me@x.social",
                actor_id="9",
            )
        )
        await session.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def src_db(tmp_path):
    url = _url(tmp_path / "src.db")
    await _seed(url)
    return url


@pytest_asyncio.fixture
async def empty_dst_db(tmp_path):
    url = _url(tmp_path / "dst.db")
    await _create_schema(url)
    return url


# --- export ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_writes_jsonl_with_rows(src_db, tmp_path):
    out = tmp_path / "dump.jsonl"
    counts = await db_port.export_jsonl(out, url=src_db)
    assert counts["meta_accounts"] == 1
    assert counts["cached_posts"] == 1
    lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 3  # meta_account + identity + post
    import json

    first = json.loads(lines[0])
    assert "table" in first and "row" in first


# --- import round-trip -----------------------------------------------------


@pytest.mark.asyncio
async def test_export_import_roundtrip_matches(src_db, empty_dst_db, tmp_path):
    out = tmp_path / "dump.jsonl"
    await db_port.export_jsonl(out, url=src_db)
    written = await db_port.import_jsonl(out, url=empty_dst_db, mode="upsert-newer")
    assert written["cached_posts"] == 1

    report = await db_port.verify(src_db, empty_dst_db)
    assert all(r["hash_match"] and r["left_rows"] == r["right_rows"] for r in report)


@pytest.mark.asyncio
async def test_import_is_idempotent(src_db, empty_dst_db, tmp_path):
    out = tmp_path / "dump.jsonl"
    await db_port.export_jsonl(out, url=src_db)
    await db_port.import_jsonl(out, url=empty_dst_db, mode="upsert-newer")
    await db_port.import_jsonl(out, url=empty_dst_db, mode="upsert-newer")
    report = await db_port.verify(src_db, empty_dst_db)
    assert all(r["left_rows"] == r["right_rows"] for r in report)


@pytest.mark.asyncio
async def test_datetime_columns_survive_roundtrip(src_db, empty_dst_db, tmp_path):
    out = tmp_path / "dump.jsonl"
    await db_port.export_jsonl(out, url=src_db)
    await db_port.import_jsonl(out, url=empty_dst_db, mode="upsert-newer")

    engine = create_async_engine(empty_dst_db)
    factory = async_sessionmaker(engine)
    async with factory() as session:
        post = await session.get(CachedPost, ("p1", 1, 1))
        assert post is not None
        assert post.created_at == datetime(2026, 7, 8, 12, 1)
        assert post.created_at.tzinfo is None  # naive UTC preserved
    await engine.dispose()


# --- import modes / guards -------------------------------------------------


@pytest.mark.asyncio
async def test_insert_only_into_nonempty_requires_force(src_db, tmp_path):
    out = tmp_path / "dump.jsonl"
    await db_port.export_jsonl(out, url=src_db)
    # src_db is non-empty; insert-only without force must refuse.
    with pytest.raises(RuntimeError, match="non-empty database"):
        await db_port.import_jsonl(out, url=src_db, mode="insert-only")


@pytest.mark.asyncio
async def test_fail_on_conflict_raises_on_existing_pk(src_db, tmp_path):
    out = tmp_path / "dump.jsonl"
    await db_port.export_jsonl(out, url=src_db)
    with pytest.raises(RuntimeError, match="already exists"):
        await db_port.import_jsonl(out, url=src_db, mode="fail-on-conflict", force=True)


@pytest.mark.asyncio
async def test_insert_only_skips_existing_with_force(src_db, tmp_path):
    out = tmp_path / "dump.jsonl"
    await db_port.export_jsonl(out, url=src_db)
    # With force, insert-only into the populated src is a no-op (PKs collide).
    written = await db_port.import_jsonl(out, url=src_db, mode="insert-only", force=True)
    assert written["cached_posts"] == 1  # rows attempted, silently ignored
    # still exactly one row
    from sqlalchemy import Table

    engine = create_async_engine(src_db)
    table: Table = Base.metadata.tables["cached_posts"]
    assert await db_port.count_rows(engine, table) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_mode_raises(src_db, tmp_path):
    out = tmp_path / "dump.jsonl"
    await db_port.export_jsonl(out, url=src_db)
    with pytest.raises(ValueError, match="Unknown import mode"):
        await db_port.import_jsonl(out, url=src_db, mode="teleport")


# --- port / diff / verify --------------------------------------------------


@pytest.mark.asyncio
async def test_port_copies_between_backends(src_db, empty_dst_db, tmp_path):
    result = await db_port.port(
        from_url=src_db,
        to_url=empty_dst_db,
        tmp_path=tmp_path / "port.jsonl",
        mode="upsert-newer",
    )
    assert result["written"]["cached_posts"] == 1
    report = await db_port.verify(src_db, empty_dst_db)
    assert all(r["hash_match"] and r["left_rows"] == r["right_rows"] for r in report)


@pytest.mark.asyncio
async def test_diff_detects_content_difference(src_db, tmp_path):
    # A second DB with a differing post body.
    other = _url(tmp_path / "other.db")
    await _seed(other, post_content="<p>DIFFERENT</p>")

    differing = await db_port.diff(src_db, other)
    tables = {r["table"] for r in differing}
    assert "cached_posts" in tables
    row = next(r for r in differing if r["table"] == "cached_posts")
    assert row["left_rows"] == row["right_rows"] == 1
    assert row["hash_match"] is False


@pytest.mark.asyncio
async def test_diff_empty_when_identical(src_db, empty_dst_db, tmp_path):
    await db_port.port(from_url=src_db, to_url=empty_dst_db, tmp_path=tmp_path / "p.jsonl")
    assert await db_port.diff(src_db, empty_dst_db) == []


def test_row_hash_stable_and_excludes_content_hash():
    a = {"id": "x", "n": 1, "content_hash": "aaa"}
    b = {"id": "x", "n": 1, "content_hash": "bbb"}
    assert db_port.row_hash(a) == db_port.row_hash(b)
    assert db_port.row_hash({"id": "x", "n": 2}) != db_port.row_hash({"id": "x", "n": 1})
