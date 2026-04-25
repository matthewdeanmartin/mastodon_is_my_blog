from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mastodon_is_my_blog.store import (
    Base,
    CachedAccount,
    CachedNotification,
    CachedPost,
    MastodonIdentity,
    MetaAccount,
)


@pytest_asyncio.fixture
async def db_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_session_factory):
    async with db_session_factory() as session:
        yield session


@pytest.fixture
def patch_async_session(monkeypatch, db_session_factory):
    def apply(*modules) -> None:
        for module in modules:
            monkeypatch.setattr(module, "async_session", db_session_factory)

    return apply


def make_meta_account(meta_id: int = 1, username: str = "default") -> MetaAccount:
    return MetaAccount(id=meta_id, username=username)


def make_identity(
    identity_id: int = 1,
    *,
    meta_account_id: int = 1,
    config_name: str | None = None,
    api_base_url: str = "https://example.social",
    client_id: str = "client-id",
    client_secret: str = "client-secret",
    access_token: str = "access-token",
    acct: str = "me@example.social",
    account_id: str = "9001",
) -> MastodonIdentity:
    return MastodonIdentity(
        id=identity_id,
        meta_account_id=meta_account_id,
        config_name=config_name,
        api_base_url=api_base_url,
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
        acct=acct,
        account_id=account_id,
    )


def make_account_data(
    account_id: str = "account-1",
    *,
    acct: str = "friend@example.social",
    display_name: str = "Friend",
    note: str = "",
    created_at: datetime | None = None,
) -> dict:
    return {
        "id": account_id,
        "acct": acct,
        "display_name": display_name,
        "avatar": "https://example.social/avatar.png",
        "url": f"https://example.social/@{acct.split('@')[0]}",
        "note": note,
        "bot": False,
        "locked": False,
        "header": "https://example.social/header.png",
        "fields": [],
        "followers_count": 10,
        "following_count": 5,
        "statuses_count": 20,
        "last_status_at": None,
        "created_at": created_at,
    }


def make_cached_account(
    account_id: str = "account-1",
    *,
    meta_account_id: int = 1,
    identity_id: int = 1,
    acct: str = "friend@example.social",
    is_following: bool = True,
    is_followed_by: bool = False,
    last_status_at: datetime | None = None,
) -> CachedAccount:
    return CachedAccount(
        id=account_id,
        meta_account_id=meta_account_id,
        mastodon_identity_id=identity_id,
        acct=acct,
        display_name=acct,
        avatar="https://example.social/avatar.png",
        url=f"https://example.social/@{acct.split('@')[0]}",
        note="",
        bot=False,
        locked=False,
        created_at=None,
        header="https://example.social/header.png",
        fields="[]",
        followers_count=10,
        following_count=5,
        statuses_count=20,
        is_following=is_following,
        is_followed_by=is_followed_by,
        last_status_at=last_status_at,
        cached_post_count=0,
        cached_reply_count=0,
    )


def make_status(
    status_id: str = "status-1",
    *,
    account_id: str = "account-1",
    acct: str = "friend@example.social",
    content: str = "<p>Hello</p>",
    created_at: datetime | None = None,
    visibility: str = "public",
    reblog: dict | None = None,
    in_reply_to_id: str | None = None,
    in_reply_to_account_id: str | None = None,
    media_attachments: list[dict] | None = None,
    tags: list[dict] | None = None,
    replies_count: int = 0,
    reblogs_count: int = 0,
    favourites_count: int = 0,
) -> dict:
    return {
        "id": status_id,
        "reblog": reblog,
        "content": content,
        "created_at": created_at or datetime(2024, 1, 1, tzinfo=timezone.utc),
        "visibility": visibility,
        "account": {"id": account_id, "acct": acct},
        "in_reply_to_id": in_reply_to_id,
        "in_reply_to_account_id": in_reply_to_account_id,
        "media_attachments": media_attachments or [],
        "tags": tags or [],
        "replies_count": replies_count,
        "reblogs_count": reblogs_count,
        "favourites_count": favourites_count,
    }


def make_cached_post(
    post_id: str = "post-1",
    *,
    meta_account_id: int = 1,
    identity_id: int = 1,
    author_acct: str = "friend@example.social",
    author_id: str = "account-1",
    actor_acct: str | None = None,
    actor_id: str | None = None,
    content: str = "<p>Hello</p>",
    is_reblog: bool = False,
    is_reply: bool = False,
    has_media: bool = False,
    has_video: bool = False,
    has_news: bool = False,
    has_tech: bool = False,
    has_link: bool = False,
    has_job: bool = False,
    has_question: bool = False,
    has_book: bool = False,
    in_reply_to_id: str | None = None,
    in_reply_to_account_id: str | None = None,
) -> CachedPost:
    return CachedPost(
        id=post_id,
        meta_account_id=meta_account_id,
        fetched_by_identity_id=identity_id,
        content=content,
        created_at=datetime(2024, 1, 1),
        visibility="public",
        author_acct=author_acct,
        author_id=author_id,
        actor_acct=actor_acct or author_acct,
        actor_id=actor_id or author_id,
        is_reblog=is_reblog,
        is_reply=is_reply,
        in_reply_to_id=in_reply_to_id,
        in_reply_to_account_id=in_reply_to_account_id,
        has_media=has_media,
        has_video=has_video,
        has_news=has_news,
        has_tech=has_tech,
        has_link=has_link,
        has_job=has_job,
        has_question=has_question,
        has_book=has_book,
        media_attachments=None,
        tags="[]",
        replies_count=0,
        reblogs_count=0,
        favourites_count=0,
    )


def make_cached_notification(
    notification_id: str = "notif-1",
    *,
    meta_account_id: int = 1,
    identity_id: int = 1,
    notification_type: str = "mention",
    created_at: datetime | None = None,
    account_id: str = "account-1",
    account_acct: str = "friend@example.social",
    status_id: str | None = None,
) -> CachedNotification:
    return CachedNotification(
        id=notification_id,
        meta_account_id=meta_account_id,
        identity_id=identity_id,
        type=notification_type,
        created_at=created_at or datetime(2024, 1, 1),
        account_id=account_id,
        account_acct=account_acct,
        status_id=status_id,
    )


def make_notification_payload(
    notification_id: str = "notif-1",
    *,
    notification_type: str = "mention",
    account_id: str = "account-1",
    account_acct: str = "friend@example.social",
    status_id: str | None = "status-1",
    created_at: datetime | None = None,
) -> dict:
    payload = {
        "id": notification_id,
        "type": notification_type,
        "account": make_account_data(account_id, acct=account_acct),
        "created_at": created_at or datetime(2024, 1, 1, tzinfo=timezone.utc),
    }
    if status_id is not None:
        payload["status"] = {"id": status_id}
    return payload
