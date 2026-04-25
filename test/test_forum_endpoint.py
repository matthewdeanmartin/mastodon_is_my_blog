"""Tests for GET /api/forum/threads endpoint."""

import json
from collections import defaultdict
from datetime import datetime
from test.conftest import make_cached_account, make_identity, make_meta_account
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from mastodon_is_my_blog import duck as duck_module
from mastodon_is_my_blog.routes.forum import get_forum_threads
from mastodon_is_my_blog.store import CachedPost

META_ID = 1


def make_thread_post(
    post_id: str,
    *,
    meta_account_id: int = META_ID,
    identity_id: int = 1,
    author_acct: str = "alice@example.social",
    author_id: str = "100",
    in_reply_to_id: str | None = None,
    root_id: str | None = None,
    root_is_partial: bool = False,
    has_question: bool = False,
    created_at: datetime | None = None,
    tags: str = "[]",
) -> CachedPost:
    rid = root_id if root_id is not None else (in_reply_to_id if in_reply_to_id else post_id)
    return CachedPost(
        id=post_id,
        meta_account_id=meta_account_id,
        fetched_by_identity_id=identity_id,
        content=f"<p>Post {post_id}</p>",
        created_at=created_at or datetime(2024, 6, 1),
        visibility="public",
        author_acct=author_acct,
        author_id=author_id,
        actor_acct=author_acct,
        actor_id=author_id,
        is_reblog=False,
        is_reply=in_reply_to_id is not None,
        in_reply_to_id=in_reply_to_id,
        in_reply_to_account_id=None,
        has_media=False,
        has_video=False,
        has_news=False,
        has_tech=False,
        has_link=False,
        has_job=False,
        has_question=has_question,
        has_book=False,
        media_attachments=None,
        tags=tags,
        replies_count=0,
        reblogs_count=0,
        favourites_count=0,
        root_id=rid,
        root_is_partial=root_is_partial,
    )


def make_meta() -> list:
    return [
        make_meta_account(meta_id=META_ID),
        make_identity(identity_id=1, meta_account_id=META_ID, acct="me@example.social"),
    ]


class FakeState:
    nlp = None


class FakeApp:
    state = FakeState()


class FakeRequest:
    app = FakeApp()


async def build_thread_summaries_from_session(db_session, meta_id: int, identity_id: int) -> list[dict]:
    """Replicate duck.forum_thread_summaries logic against the in-memory SQLite session."""
    rows = (
        await db_session.execute(
            select(CachedPost).where(
                CachedPost.meta_account_id == meta_id,
                CachedPost.fetched_by_identity_id == identity_id,
                CachedPost.is_reblog == False,  # noqa: E712
                CachedPost.root_id.is_not(None),
            )
        )
    ).scalars().all()

    by_root: dict[str, list] = defaultdict(list)
    for p in rows:
        by_root[p.root_id].append(p)

    results = []
    for root_id, posts in by_root.items():
        unique_authors = {p.author_acct for p in posts}
        if len(posts) < 1:
            continue

        root_post = next((p for p in posts if p.id == root_id), posts[0])
        replies = [p for p in posts if p.id != root_id]
        latest_reply = max((p.created_at for p in replies), default=None)

        all_tags: set[str] = set()
        for p in posts:
            if p.tags and p.tags != "[]":
                try:
                    all_tags.update(t.lower() for t in json.loads(p.tags))
                except Exception:
                    pass

        uncommon: list[str] = []
        if root_post.thread_uncommon_words:
            try:
                uncommon = json.loads(root_post.thread_uncommon_words)
            except Exception:
                pass

        results.append({
            "root_id": root_id,
            "reply_count": len(replies),
            "unique_participants": len(unique_authors),
            "latest_reply_at": latest_reply.isoformat() if latest_reply else None,
            "author_acct": root_post.author_acct,
            "root_created_at": root_post.created_at.isoformat() if root_post.created_at else None,
            "root_content": root_post.content,
            "has_question": bool(root_post.has_question),
            "root_tags": root_post.tags,
            "uncommon_words": uncommon,
            "root_is_partial": bool(root_post.root_is_partial),
            "tags": all_tags,
            "participants": {p.author_acct for p in posts},
        })

    return results


async def call_endpoint(
    db_session,
    monkeypatch,
    *,
    top_filter: str = "recent",
    hashtag: list | None = None,
    uncommon_word: list | None = None,
    root_instance: list | None = None,
    before: str | None = None,
) -> dict:
    import mastodon_is_my_blog.routes.forum as forum_module
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def session_ctx():
        yield db_session

    class WrappedFactory:
        def __call__(self):
            return session_ctx()

    monkeypatch.setattr(forum_module, "async_session", WrappedFactory())

    async def fake_forum_thread_summaries(meta_id, identity_id, include_content_hub=False):
        return await build_thread_summaries_from_session(db_session, meta_id, identity_id)

    async def fake_forum_friend_reply_counts(meta_id, identity_id, root_ids, following_accts):
        return {}

    monkeypatch.setattr(duck_module, "forum_thread_summaries", fake_forum_thread_summaries)
    monkeypatch.setattr(duck_module, "forum_friend_reply_counts", fake_forum_friend_reply_counts)

    meta = SimpleNamespace(id=META_ID, username="test-meta")
    return await get_forum_threads(
        request=FakeRequest(),
        identity_id=1,
        top_filter=top_filter,
        hashtag=hashtag or [],
        uncommon_word=uncommon_word or [],
        root_instance=root_instance or [],
        limit=25,
        before=before,
        meta=meta,
    )


@pytest.mark.asyncio
async def test_empty_returns_no_items(db_session, monkeypatch):
    db_session.add_all(make_meta())
    await db_session.commit()

    result = await call_endpoint(db_session, monkeypatch)
    assert result["items"] == []
    assert result["next_cursor"] is None
    assert "facets" in result


@pytest.mark.asyncio
async def test_root_post_appears_as_thread(db_session, monkeypatch):
    db_session.add_all([
        *make_meta(),
        make_thread_post("root-1", author_acct="alice@example.social"),
    ])
    await db_session.commit()

    result = await call_endpoint(db_session, monkeypatch)
    assert len(result["items"]) == 1
    assert result["items"][0]["root_id"] == "root-1"


@pytest.mark.asyncio
async def test_reply_is_grouped_under_root(db_session, monkeypatch):
    db_session.add_all([
        *make_meta(),
        make_thread_post("root-1"),
        make_thread_post("reply-1", in_reply_to_id="root-1", root_id="root-1", author_acct="bob@example.social"),
    ])
    await db_session.commit()

    result = await call_endpoint(db_session, monkeypatch)
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["root_id"] == "root-1"
    assert item["reply_count"] == 1


@pytest.mark.asyncio
async def test_questions_filter(db_session, monkeypatch):
    db_session.add_all([
        *make_meta(),
        make_thread_post("q-root", has_question=True),
        make_thread_post("plain-root"),
    ])
    await db_session.commit()

    result = await call_endpoint(db_session, monkeypatch, top_filter="questions")
    ids = [item["root_id"] for item in result["items"]]
    assert "q-root" in ids
    assert "plain-root" not in ids


@pytest.mark.asyncio
async def test_friends_started_filter(db_session, monkeypatch):
    db_session.add_all([
        *make_meta(),
        make_cached_account("acc-friend", meta_account_id=META_ID, identity_id=1, acct="friend@example.social", is_following=True),
        make_cached_account("acc-stranger", meta_account_id=META_ID, identity_id=1, acct="stranger@example.social", is_following=False),
        make_thread_post("friend-root", author_acct="friend@example.social", author_id="acc-friend"),
        make_thread_post("stranger-root", author_acct="stranger@example.social", author_id="acc-stranger"),
    ])
    await db_session.commit()

    result = await call_endpoint(db_session, monkeypatch, top_filter="friends_started")
    ids = [item["root_id"] for item in result["items"]]
    assert "friend-root" in ids
    assert "stranger-root" not in ids


@pytest.mark.asyncio
async def test_mine_filter(db_session, monkeypatch):
    db_session.add_all([
        *make_meta(),
        make_thread_post("my-root", author_acct="me@example.social"),
        make_thread_post("other-root", author_acct="other@example.social"),
    ])
    await db_session.commit()

    result = await call_endpoint(db_session, monkeypatch, top_filter="mine")
    ids = [item["root_id"] for item in result["items"]]
    assert "my-root" in ids
    assert "other-root" not in ids


@pytest.mark.asyncio
async def test_partial_thread_badge(db_session, monkeypatch):
    db_session.add_all([
        *make_meta(),
        make_thread_post("partial-root", root_is_partial=True),
    ])
    await db_session.commit()

    result = await call_endpoint(db_session, monkeypatch)
    assert len(result["items"]) == 1
    assert result["items"][0]["root_is_partial"] is True


@pytest.mark.asyncio
async def test_hashtag_facet_chip_filter(db_session, monkeypatch):
    db_session.add_all([
        *make_meta(),
        make_thread_post("cats-root", tags='["cats"]'),
        make_thread_post("dogs-root", tags='["dogs"]'),
    ])
    await db_session.commit()

    result = await call_endpoint(db_session, monkeypatch, hashtag=["cats"])
    ids = [item["root_id"] for item in result["items"]]
    assert "cats-root" in ids
    assert "dogs-root" not in ids


@pytest.mark.asyncio
async def test_facets_computed_over_filtered_set(db_session, monkeypatch):
    db_session.add_all([
        *make_meta(),
        make_thread_post("q1", has_question=True, tags='["python"]'),
        make_thread_post("q2", has_question=True, tags='["rust"]'),
        make_thread_post("plain", has_question=False, tags='["java"]'),
    ])
    await db_session.commit()

    result = await call_endpoint(db_session, monkeypatch, top_filter="questions")
    facet_tags = {h["tag"] for h in result["facets"]["hashtags"]}
    assert "java" not in facet_tags
    assert "python" in facet_tags or "rust" in facet_tags


@pytest.mark.asyncio
async def test_participating_filter(db_session, monkeypatch):
    db_session.add_all([
        *make_meta(),
        make_thread_post("their-root", author_acct="other@example.social"),
        make_thread_post("my-reply", in_reply_to_id="their-root", root_id="their-root", author_acct="me@example.social"),
        make_thread_post("unrelated-root", author_acct="stranger@example.social"),
    ])
    await db_session.commit()

    result = await call_endpoint(db_session, monkeypatch, top_filter="participating")
    ids = [item["root_id"] for item in result["items"]]
    assert "their-root" in ids
    assert "unrelated-root" not in ids
