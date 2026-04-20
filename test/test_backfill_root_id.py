"""Unit tests for backfill_root_id logic."""

import asyncio
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mastodon_is_my_blog.store import Base, CachedPost


def make_post(post_id, meta_id=1, identity_id=1, in_reply_to_id=None):
    return CachedPost(
        id=post_id,
        meta_account_id=meta_id,
        fetched_by_identity_id=identity_id,
        content="<p>test</p>",
        created_at=datetime(2024, 1, 1),
        visibility="public",
        author_acct="user@example.social",
        author_id="1",
        actor_acct="user@example.social",
        actor_id="1",
        is_reblog=False,
        is_reply=in_reply_to_id is not None,
        in_reply_to_id=in_reply_to_id,
        in_reply_to_account_id=None,
        media_attachments=None,
        tags="[]",
        replies_count=0,
        reblogs_count=0,
        favourites_count=0,
    )


@pytest_asyncio.fixture
async def engine():
    e = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with e.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield e
    await e.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def run_backfill(session_factory):
    """Run the backfill logic inline (without module-level async_session)."""
    from sqlalchemy import and_, update

    async with session_factory() as session:
        stmt = select(
            CachedPost.id,
            CachedPost.meta_account_id,
            CachedPost.in_reply_to_id,
            CachedPost.root_id,
        )
        rows = (await session.execute(stmt)).all()

    post_map = {}
    for row in rows:
        post_map[(row.meta_account_id, row.id)] = row.in_reply_to_id

    updates = []
    for row in rows:
        if row.root_id is not None:
            continue
        if row.in_reply_to_id is None:
            updates.append({"post_id": row.id, "meta_id": row.meta_account_id, "root_id": row.id, "partial": False})
        else:
            current_id = row.in_reply_to_id
            meta_id = row.meta_account_id
            visited = {row.id}
            partial = False
            while True:
                if current_id in visited:
                    partial = True
                    break
                visited.add(current_id)
                parent_reply = post_map.get((meta_id, current_id))
                if parent_reply is None:
                    if (meta_id, current_id) not in post_map:
                        partial = True
                    break
                current_id = parent_reply
            updates.append({"post_id": row.id, "meta_id": meta_id, "root_id": current_id, "partial": partial})

    async with session_factory() as session:
        for item in updates:
            await session.execute(
                update(CachedPost)
                .where(and_(CachedPost.id == item["post_id"], CachedPost.meta_account_id == item["meta_id"]))
                .values(root_id=item["root_id"], root_is_partial=item["partial"])
            )
        await session.commit()


@pytest.mark.asyncio
async def test_self_root(session_factory):
    async with session_factory() as session:
        session.add(make_post("root-1"))
        await session.commit()

    await run_backfill(session_factory)

    async with session_factory() as session:
        post = (await session.execute(select(CachedPost).where(CachedPost.id == "root-1"))).scalar_one()
        assert post.root_id == "root-1"
        assert post.root_is_partial is False


@pytest.mark.asyncio
async def test_single_hop_reply(session_factory):
    async with session_factory() as session:
        session.add(make_post("root-1"))
        session.add(make_post("reply-1", in_reply_to_id="root-1"))
        await session.commit()

    await run_backfill(session_factory)

    async with session_factory() as session:
        reply = (await session.execute(select(CachedPost).where(CachedPost.id == "reply-1"))).scalar_one()
        assert reply.root_id == "root-1"
        assert reply.root_is_partial is False


@pytest.mark.asyncio
async def test_multi_hop_reply(session_factory):
    async with session_factory() as session:
        session.add(make_post("root-1"))
        session.add(make_post("reply-1", in_reply_to_id="root-1"))
        session.add(make_post("reply-2", in_reply_to_id="reply-1"))
        await session.commit()

    await run_backfill(session_factory)

    async with session_factory() as session:
        deep = (await session.execute(select(CachedPost).where(CachedPost.id == "reply-2"))).scalar_one()
        assert deep.root_id == "root-1"
        assert deep.root_is_partial is False


@pytest.mark.asyncio
async def test_partial_chain_missing_ancestor(session_factory):
    # Only reply-1 and reply-2 are cached; root "missing-root" is not.
    async with session_factory() as session:
        session.add(make_post("reply-1", in_reply_to_id="missing-root"))
        session.add(make_post("reply-2", in_reply_to_id="reply-1"))
        await session.commit()

    await run_backfill(session_factory)

    async with session_factory() as session:
        r1 = (await session.execute(select(CachedPost).where(CachedPost.id == "reply-1"))).scalar_one()
        r2 = (await session.execute(select(CachedPost).where(CachedPost.id == "reply-2"))).scalar_one()
        assert r1.root_id == "missing-root"
        assert r1.root_is_partial is True
        assert r2.root_id == "missing-root"
        assert r2.root_is_partial is True


@pytest.mark.asyncio
async def test_idempotent(session_factory):
    async with session_factory() as session:
        session.add(make_post("root-1"))
        session.add(make_post("reply-1", in_reply_to_id="root-1"))
        await session.commit()

    await run_backfill(session_factory)
    await run_backfill(session_factory)  # second run should be a no-op

    async with session_factory() as session:
        reply = (await session.execute(select(CachedPost).where(CachedPost.id == "reply-1"))).scalar_one()
        assert reply.root_id == "root-1"
