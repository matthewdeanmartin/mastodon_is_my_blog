"""
Regression tests for CachedPost boolean filter queries.

These tests use a real in-memory SQLite database to verify that queries using
.is_(True/False/None) produce correct SQL — as opposed to the Python `is` operator,
which evaluates at Python-level and silently drops filter conditions.

The bug this guards against: `CachedPost.is_reblog is False` evaluates to the Python
boolean `False`, which SQLAlchemy treats as a no-op placeholder, effectively removing
the filter and causing `scope = and_(..., False)` to match 0 rows.
"""

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import and_, desc, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mastodon_is_my_blog.store import Base, CachedPost


@pytest_asyncio.fixture
async def in_memory_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


def make_post(
    post_id: str,
    *,
    meta_account_id: int = 1,
    fetched_by_identity_id: int = 1,
    is_reblog: bool = False,
    is_reply: bool = False,
    has_media: bool = False,
    has_link: bool = False,
    has_video: bool = False,
    has_news: bool = False,
    has_tech: bool = False,
    has_question: bool = False,
    in_reply_to_id: str | None = None,
    content: str = "<p>Test post</p>",
    author_acct: str = "alice@example.com",
    author_id: str = "author-1",
    created_at: datetime | None = None,
) -> CachedPost:
    return CachedPost(
        id=post_id,
        meta_account_id=meta_account_id,
        fetched_by_identity_id=fetched_by_identity_id,
        is_reblog=is_reblog,
        is_reply=is_reply,
        has_media=has_media,
        has_link=has_link,
        has_video=has_video,
        has_news=has_news,
        has_tech=has_tech,
        has_question=has_question,
        in_reply_to_id=in_reply_to_id,
        content=content,
        author_acct=author_acct,
        author_id=author_id,
        visibility="public",
        created_at=created_at or datetime(2024, 1, 1, 12, 0, 0),
        replies_count=0,
        reblogs_count=0,
        favourites_count=0,
        tags="[]",
    )


@pytest.mark.asyncio
async def test_is_reblog_false_filter_returns_non_reblogs(in_memory_session) -> None:
    """is_(False) on is_reblog must match rows where is_reblog=0, not match 0 rows."""
    in_memory_session.add(make_post("original", is_reblog=False))
    in_memory_session.add(make_post("reblog", is_reblog=True))
    await in_memory_session.flush()

    result = await in_memory_session.execute(
        select(CachedPost).where(CachedPost.is_reblog.is_(False))
    )
    rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].id == "original"


@pytest.mark.asyncio
async def test_is_reply_false_filter_returns_root_posts(in_memory_session) -> None:
    """is_(False) on is_reply must return root posts only."""
    in_memory_session.add(make_post("root", is_reply=False))
    in_memory_session.add(make_post("reply", is_reply=True))
    await in_memory_session.flush()

    result = await in_memory_session.execute(
        select(CachedPost).where(CachedPost.is_reply.is_(False))
    )
    rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].id == "root"


@pytest.mark.asyncio
async def test_scope_with_is_reblog_false_returns_data(in_memory_session) -> None:
    """
    Regression: the storms endpoint scope used `CachedPost.is_reblog is False`
    which evaluated to the Python bool False, making and_(..., False) produce 0 rows.
    Verify that .is_(False) in scope returns the scoped posts correctly.
    """
    in_memory_session.add(make_post("p1", meta_account_id=1, fetched_by_identity_id=1))
    in_memory_session.add(make_post("p2", meta_account_id=2, fetched_by_identity_id=1))
    await in_memory_session.flush()

    scope = and_(
        CachedPost.meta_account_id == 1,
        CachedPost.fetched_by_identity_id == 1,
        CachedPost.is_reblog.is_(False),
    )

    result = await in_memory_session.execute(select(CachedPost).where(scope))
    rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].id == "p1"


@pytest.mark.asyncio
async def test_in_reply_to_id_is_none_filter_returns_root_posts(in_memory_session) -> None:
    """in_reply_to_id.is_(None) must produce IS NULL in SQL, not match 0 rows."""
    in_memory_session.add(make_post("root", in_reply_to_id=None))
    in_memory_session.add(make_post("reply", in_reply_to_id="root"))
    await in_memory_session.flush()

    result = await in_memory_session.execute(
        select(CachedPost).where(CachedPost.in_reply_to_id.is_(None))
    )
    rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].id == "root"


@pytest.mark.asyncio
async def test_in_reply_to_id_is_not_none_filter_returns_replies(in_memory_session) -> None:
    """in_reply_to_id.is_not(None) must produce IS NOT NULL."""
    in_memory_session.add(make_post("root", in_reply_to_id=None))
    in_memory_session.add(make_post("reply", in_reply_to_id="root"))
    await in_memory_session.flush()

    result = await in_memory_session.execute(
        select(CachedPost).where(CachedPost.in_reply_to_id.is_not(None))
    )
    rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].id == "reply"


@pytest.mark.asyncio
async def test_has_link_true_filter_returns_link_posts(in_memory_session) -> None:
    """is_(True) on has_link must return posts where has_link=1."""
    in_memory_session.add(make_post("with-link", has_link=True))
    in_memory_session.add(make_post("no-link", has_link=False))
    await in_memory_session.flush()

    result = await in_memory_session.execute(
        select(CachedPost).where(CachedPost.has_link.is_(True))
    )
    rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].id == "with-link"


@pytest.mark.asyncio
async def test_shorts_filter_returns_only_qualifying_posts(in_memory_session) -> None:
    """
    The 'shorts' filter requires: not reply, not reblog, no media, no video, no link,
    and content length < 500. Verify all conditions work via .is_(False).
    """
    in_memory_session.add(make_post("short", content="<p>A short post.</p>"))
    in_memory_session.add(make_post("reply-post", is_reply=True, content="<p>Reply</p>"))
    in_memory_session.add(make_post("reblog-post", is_reblog=True, content="<p>Reblog</p>"))
    in_memory_session.add(make_post("media-post", has_media=True, content="<p>Has media</p>"))
    in_memory_session.add(make_post("link-post", has_link=True, content="<p>Has link</p>"))
    await in_memory_session.flush()

    shorts_filter = and_(
        CachedPost.is_reply.is_(False),
        CachedPost.is_reblog.is_(False),
        CachedPost.has_media.is_(False),
        CachedPost.has_video.is_(False),
        CachedPost.has_link.is_(False),
        func.length(CachedPost.content) < 500,
    )

    result = await in_memory_session.execute(
        select(CachedPost).where(shorts_filter)
    )
    rows = result.scalars().all()

    assert len(rows) == 1
    assert rows[0].id == "short"


@pytest.mark.asyncio
async def test_filter_category_true_flags(in_memory_session) -> None:
    """Each has_* True filter must return the right rows."""
    in_memory_session.add(make_post("news", has_news=True))
    in_memory_session.add(make_post("tech", has_tech=True))
    in_memory_session.add(make_post("media", has_media=True))
    in_memory_session.add(make_post("video", has_video=True))
    in_memory_session.add(make_post("question", has_question=True))
    in_memory_session.add(make_post("plain"))
    await in_memory_session.flush()

    for flag_col, expected_id in [
        (CachedPost.has_news, "news"),
        (CachedPost.has_tech, "tech"),
        (CachedPost.has_media, "media"),
        (CachedPost.has_video, "video"),
        (CachedPost.has_question, "question"),
    ]:
        result = await in_memory_session.execute(
            select(CachedPost).where(flag_col.is_(True))
        )
        rows = result.scalars().all()
        assert len(rows) == 1, f"Expected 1 row for {flag_col}, got {len(rows)}"
        assert rows[0].id == expected_id


@pytest.mark.asyncio
async def test_storms_scope_returns_nonzero_results(in_memory_session) -> None:
    """
    Regression: storms scope and_(meta==1, identity==1, is_reblog.is_(False))
    must not silently drop to 0 rows when posts exist.
    """
    for i in range(3):
        in_memory_session.add(
            make_post(
                f"storm-{i}",
                meta_account_id=1,
                fetched_by_identity_id=1,
                in_reply_to_id=None,
                has_link=False,
                content="<p>" + "x" * 600 + "</p>",  # Long enough for storm
            )
        )
    await in_memory_session.flush()

    scope = and_(
        CachedPost.meta_account_id == 1,
        CachedPost.fetched_by_identity_id == 1,
        CachedPost.is_reblog.is_(False),
    )

    roots_query = select(CachedPost).where(
        and_(
            scope,
            CachedPost.in_reply_to_id.is_(None),
            CachedPost.has_link.is_(False),
            func.length(CachedPost.content) >= 500,
        )
    ).order_by(desc(CachedPost.created_at))

    result = await in_memory_session.execute(roots_query)
    roots = result.scalars().all()

    assert len(roots) == 3
