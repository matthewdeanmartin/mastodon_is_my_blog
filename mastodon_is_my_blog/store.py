from __future__ import annotations
# mastodon_is_my_blog/store.py
import logging
import os
from datetime import datetime
from typing import List, Optional

import dotenv
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
    func,
    insert,
    select,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from mastodon_is_my_blog.account_config import normalize_base_url
from mastodon_is_my_blog.credentials import set_credential
from mastodon_is_my_blog.datetime_helpers import utc_now
from mastodon_is_my_blog.utils.settings_loader import (
    load_configured_identities,
    resolve_identity_config,
)

logging.basicConfig()
# logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)

dotenv.load_dotenv()

from mastodon_is_my_blog.db_path import get_default_db_url
DB_URL = get_default_db_url()
# Database setup
engine = create_async_engine(
    DB_URL,
    echo=False,
)


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragmas(dbapi_conn, _):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA mmap_size=268435456")
    cursor.execute("PRAGMA cache_size=-64000")
    cursor.close()


async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Token(Base):
    __tablename__ = "tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)
    value: Mapped[str] = mapped_column(String(500))


class MetaAccount(Base):
    """
    The root 'Real World Person'.
    Holds multiple Mastodon Identities.
    """

    __tablename__ = "meta_accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    # Relationships
    identities: Mapped[List["MastodonIdentity"]] = relationship(
        "MastodonIdentity", back_populates="meta_account", cascade="all, delete-orphan"
    )


class MastodonIdentity(Base):
    """
    A specific account on a specific Mastodon instance.
    Replaces the old 'Token' table.
    """

    __tablename__ = "mastodon_identities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    meta_account_id: Mapped[int] = mapped_column(
        ForeignKey("meta_accounts.id"), index=True
    )
    config_name: Mapped[str | None] = mapped_column(String, index=True, nullable=True)

    # Credential Details
    api_base_url: Mapped[str] = mapped_column(String)  # e.g. https://mastodon.social
    client_id: Mapped[str] = mapped_column(String)
    client_secret: Mapped[str] = mapped_column(String)
    access_token: Mapped[str] = mapped_column(String)

    # Account Info
    acct: Mapped[str] = mapped_column(String)  # user@instance
    account_id: Mapped[str] = mapped_column(String)  # Numeric ID on that instance

    meta_account: Mapped["MetaAccount"] = relationship(
        "MetaAccount", back_populates="identities"
    )


class CachedAccount(Base):
    """Stores friends, followers, and active posters for the Blog Roll
    Scoped by MetaAccount so User A's notes on @Gargron don't leak to User B.
    """

    __tablename__ = "cached_accounts"

    # Identity ID to the Primary Key
    id: Mapped[str] = mapped_column(
        String, primary_key=True
    )  # The ID on the source instance
    meta_account_id: Mapped[int] = mapped_column(
        ForeignKey("meta_accounts.id"), primary_key=True
    )
    mastodon_identity_id: Mapped[int] = mapped_column(
        ForeignKey("mastodon_identities.id"), primary_key=True
    )

    acct: Mapped[str] = mapped_column(String, index=True)
    display_name: Mapped[str] = mapped_column(String)
    avatar: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    note: Mapped[str] = mapped_column(Text, default="")  # Bio/description

    # Extended Profile Info
    bot: Mapped[bool] = mapped_column(Boolean, default=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    header: Mapped[str] = mapped_column(String, default="")
    fields: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of field objs
    followers_count: Mapped[int] = mapped_column(Integer, default=0)
    following_count: Mapped[int] = mapped_column(Integer, default=0)
    statuses_count: Mapped[int] = mapped_column(Integer, default=0)

    # Relationship flags
    is_following: Mapped[bool] = mapped_column(Boolean, default=False)
    is_followed_by: Mapped[bool] = mapped_column(Boolean, default=False)

    # Activity tracking for Blog Roll
    last_status_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )  # Added index here for the blogroll sort

    # Materialized post stats — updated at sync time, used for chatty/broadcaster filters
    cached_post_count: Mapped[int] = mapped_column(Integer, default=0)
    cached_reply_count: Mapped[int] = mapped_column(Integer, default=0)


class CachedPost(Base):
    __tablename__ = "cached_posts"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # Mastodon ID
    meta_account_id: Mapped[int] = mapped_column(
        ForeignKey("meta_accounts.id"), primary_key=True
    )
    fetched_by_identity_id: Mapped[int] = mapped_column(
        ForeignKey("mastodon_identities.id"), primary_key=True
    )

    # Which of the MetaAccount's identities fetched this?
    # fetched_by_identity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text)

    # Content Hub discovery metadata
    discovery_source: Mapped[str] = mapped_column(
        String(20), default="timeline"
    )  # timeline | hashtag | search
    content_hub_only: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    visibility: Mapped[str] = mapped_column(String(20))

    # Metadata for filtering
    author_acct: Mapped[str] = mapped_column(String, index=True)
    author_id: Mapped[str] = mapped_column(String, index=True)

    is_reblog: Mapped[bool] = mapped_column(Boolean, default=False)

    # Threading logic
    is_reply: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # Track replies to others
    in_reply_to_id: Mapped[str | None] = mapped_column(String, nullable=True)
    in_reply_to_account_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Content Flags
    has_media: Mapped[bool] = mapped_column(Boolean, default=False)  # Images
    has_video: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # Youtube or video attachment
    has_news: Mapped[bool] = mapped_column(Boolean, default=False)  # News domains
    has_tech: Mapped[bool] = mapped_column(Boolean, default=False)  # Github/Pypi etc

    has_link: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # Generic 3rd party links
    has_question: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # Contains questions

    # Store media attachments as JSON string
    media_attachments: Mapped[str | None] = mapped_column(Text, nullable=True)

    tags: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # JSON list of hashtags

    # Analytics / Context
    replies_count: Mapped[int] = mapped_column(Integer, default=0)
    reblogs_count: Mapped[int] = mapped_column(Integer, default=0)
    favourites_count: Mapped[int] = mapped_column(Integer, default=0)

    # Indexes need to include meta_account_id for performance
    __table_args__ = (
        Index("ix_posts_meta_created", "meta_account_id", "created_at"),
        Index("ix_posts_meta_author", "meta_account_id", "author_acct", "created_at"),
        Index("ix_posts_meta_clean", "meta_account_id", "is_reblog", "is_reply"),
        Index("ix_posts_meta_identity_created", "meta_account_id", "fetched_by_identity_id", "created_at"),
        Index("ix_posts_meta_identity_author", "meta_account_id", "fetched_by_identity_id", "author_acct", "created_at"),
        Index("ix_posts_in_reply_to", "meta_account_id", "fetched_by_identity_id", "in_reply_to_id"),
        Index("ix_posts_content_hub_only", "meta_account_id", "fetched_by_identity_id", "content_hub_only"),
    )

    # Define Composite Indexes to speed up specific query patterns
    # __table_args__ = (
    #     # Main Feed: "Show me posts sorted by date"
    #     Index("ix_posts_created_at", "created_at"),
    #     # User Profile: "Show me THIS user's posts, sorted by date"
    #     Index("ix_posts_author_created", "author_acct", "created_at"),
    #     # Covering indexes for COUNT queries (add columns used in WHERE)
    #     # These help avoid table lookups during counts
    #     Index(
    #         "ix_posts_storms_count",
    #         "is_reblog",
    #         "in_reply_to_id",
    #         "has_link",
    #         "author_acct",  # Added for user filtering
    #     ),
    #     # Optimized filter indexes with author for user-specific queries
    #     Index("ix_posts_news_author", "has_news", "author_acct", "created_at"),
    #     Index("ix_posts_tech_author", "has_tech", "author_acct", "created_at"),
    #     Index("ix_posts_media_author", "has_media", "author_acct", "created_at"),
    #     Index("ix_posts_video_author", "has_video", "author_acct", "created_at"),
    #     Index("ix_posts_links_author", "has_link", "author_acct", "created_at"),
    #     Index("ix_posts_questions_author", "has_question", "author_acct", "created_at"),
    #     Index("ix_posts_reply_author", "is_reply", "author_acct", "created_at"),
    #     # Compound index for "clean feed" queries (most common)
    #     Index(
    #         "ix_posts_clean_feed_optimized",
    #         "author_acct",
    #         "is_reblog",
    #         "is_reply",
    #         "created_at",
    #     ),
    # )


class CachedNotification(Base):
    """
    Stores notifications from Mastodon API.
    Enables flexible querying for top friends and interaction tracking.
    """

    __tablename__ = "cached_notifications"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # Notification ID
    meta_account_id: Mapped[int] = mapped_column(
        ForeignKey("meta_accounts.id"), primary_key=True
    )
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("mastodon_identities.id"), primary_key=True
    )

    # Notification metadata
    type: Mapped[str] = mapped_column(
        String, index=True
    )  # mention, favourite, reblog, status, follow
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    # Who interacted with me
    account_id: Mapped[str] = mapped_column(
        String, index=True
    )  # The person who triggered notification
    account_acct: Mapped[str] = mapped_column(String, index=True)  # Their @handle

    # What they interacted with (nullable for follow notifications)
    status_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    __table_args__ = (
        Index("ix_notif_meta_identity_type", "meta_account_id", "identity_id", "type"),
        Index("ix_notif_account_created", "account_id", "created_at"),
    )


class CachedLinkPreview(Base):
    """
    Persistent link-preview cache.  One row per canonicalized URL.
    TTLs:  ok → 7d fresh / 30d stale-while-revalidate
           error → 30 min negative cache
           blocked → 24 h negative cache
    """

    __tablename__ = "cached_link_previews"

    url_key: Mapped[str] = mapped_column(String, primary_key=True)
    final_url: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    site_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    image: Mapped[str | None] = mapped_column(String, nullable=True)
    favicon: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error | blocked
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_card_expires", "expires_at"),)


class AppState(Base):
    """
    Sync state. Key needs to be composite now to track sync per identity.
    """

    __tablename__ = "app_state"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    # Key format suggestion: "timeline:{meta_id}:{identity_id}"
    last_sync: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ContentHubGroup(Base):
    """
    A named bundle of hashtags / search terms forming a Content Hub group.
    client_bundle groups are per-identity and editable; server_follow groups
    are imported read-only from the identity's followed hashtags.
    """

    __tablename__ = "content_hub_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meta_account_id: Mapped[int] = mapped_column(
        ForeignKey("meta_accounts.id"), index=True
    )
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("mastodon_identities.id"), index=True
    )
    name: Mapped[str] = mapped_column(String)
    slug: Mapped[str] = mapped_column(String)
    source_type: Mapped[str] = mapped_column(String(20))  # client_bundle | server_follow
    is_read_only: Mapped[bool] = mapped_column(Boolean, default=False)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    terms: Mapped[List["ContentHubGroupTerm"]] = relationship(
        "ContentHubGroupTerm", back_populates="group", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_hub_groups_identity", "meta_account_id", "identity_id"),
        Index("ix_hub_groups_slug", "meta_account_id", "identity_id", "slug"),
    )


class ContentHubGroupTerm(Base):
    """
    A single hashtag or raw search query belonging to a ContentHubGroup.
    """

    __tablename__ = "content_hub_group_terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("content_hub_groups.id", ondelete="CASCADE"), index=True
    )
    term: Mapped[str] = mapped_column(String)
    term_type: Mapped[str] = mapped_column(String(20))  # hashtag | search
    normalized_term: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    group: Mapped["ContentHubGroup"] = relationship(
        "ContentHubGroup", back_populates="terms"
    )


class ContentHubPostMatch(Base):
    """
    Records that a cached post matched a Content Hub group term.
    Avoids recomputing matches on every request and preserves raw-search history.
    """

    __tablename__ = "content_hub_post_matches"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("content_hub_groups.id", ondelete="CASCADE"), primary_key=True
    )
    post_id: Mapped[str] = mapped_column(String, primary_key=True)
    meta_account_id: Mapped[int] = mapped_column(
        ForeignKey("meta_accounts.id"), primary_key=True
    )
    fetched_by_identity_id: Mapped[int] = mapped_column(
        ForeignKey("mastodon_identities.id")
    )
    matched_term_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_hub_group_terms.id"), nullable=True
    )
    matched_via: Mapped[str] = mapped_column(String(20))  # hashtag | search
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (
        Index("ix_hub_matches_group_post", "group_id", "meta_account_id"),
        Index("ix_hub_matches_post", "post_id", "meta_account_id"),
    )


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_or_create_default_meta_account() -> MetaAccount:
    """Helper for the single-user local install scenario"""
    async with async_session() as session:
        stmt = select(MetaAccount).where(MetaAccount.username == "default")
        meta = (await session.execute(stmt)).scalar_one_or_none()
        if not meta:
            meta = MetaAccount(username="default")
            session.add(meta)
            await session.commit()
            await session.refresh(meta)
        return meta


async def sync_configured_identities() -> None:
    """
    Load configured identities and ensure the default meta account matches them.
    """
    configured_identities = load_configured_identities()

    async with async_session() as session:
        # Get or create default meta account
        stmt = select(MetaAccount).where(MetaAccount.username == "default")
        meta = (await session.execute(stmt)).scalar_one_or_none()
        if not meta:
            meta = MetaAccount(username="default")
            session.add(meta)
            await session.flush()

        existing_identities = (
            await session.execute(
                select(MastodonIdentity).where(MastodonIdentity.meta_account_id == meta.id)
            )
        ).scalars().all()

        existing_by_name = {
            identity.config_name: identity
            for identity in existing_identities
            if identity.config_name
        }
        legacy_by_signature = {
            (normalize_base_url(identity.api_base_url), identity.client_id): identity
            for identity in existing_identities
            if not identity.config_name
        }

        configured_names = set(configured_identities)
        for name, config in configured_identities.items():
            existing = existing_by_name.get(name)
            if existing is None:
                existing = legacy_by_signature.get((config.base_url, config.client_id))

            if existing:
                existing.config_name = name
                existing.api_base_url = config.base_url
                existing.client_id = config.client_id
                existing.client_secret = ""
                existing.access_token = ""
                logging.info("Updated configured identity: %s", name)
            else:
                new_identity = MastodonIdentity(
                    meta_account_id=meta.id,
                    config_name=name,
                    api_base_url=config.base_url,
                    client_id=config.client_id,
                    client_secret="",
                    access_token="",
                    acct=f"{name.lower()}@unknown",  # Placeholder
                    account_id="0",  # Placeholder
                )
                session.add(new_identity)
                logging.info("Created configured identity: %s", name)

        for identity in existing_identities:
            if identity.config_name and identity.config_name not in configured_names:
                await session.delete(identity)

        await session.commit()


async def bootstrap_identities_from_env() -> None:
    await sync_configured_identities()


async def get_default_identity() -> Optional[MastodonIdentity]:
    """
    Gets the first identity for the default meta account.
    Useful for backwards compatibility with single-user mode.
    """
    async with async_session() as session:
        stmt = select(MetaAccount).where(MetaAccount.username == "default")
        meta = (await session.execute(stmt)).scalar_one_or_none()
        if not meta:
            return None

        stmt = (
            select(MastodonIdentity)
            .where(MastodonIdentity.meta_account_id == meta.id)
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


# --- Sync State Logic ---
async def get_last_sync(key: str = "default") -> Optional[datetime]:
    async with async_session() as session:
        res = await session.execute(select(AppState).where(AppState.key == key))
        state = res.scalar_one_or_none()
        return state.last_sync if state else None


async def update_last_sync(key: str) -> None:
    async with async_session() as session:
        res = await session.execute(select(AppState).where(AppState.key == key))
        state = res.scalar_one_or_none()
        if state:
            state.last_sync = utc_now()
        else:
            session.add(AppState(key=key, last_sync=utc_now()))
        await session.commit()


# --- Token Helpers ---
async def get_token(key: str = "mastodon_access_token") -> Optional[str]:
    identity = await get_default_identity()
    if identity:
        config = resolve_identity_config(
            identity.config_name,
            base_url=identity.api_base_url,
        )
        if config and config.access_token:
            return config.access_token

    async with async_session() as session:
        result = await session.execute(select(Token).where(Token.key == key))
        token = result.scalar_one_or_none()
        return token.value if token else os.environ.get("MASTODON_ACCESS_TOKEN")


async def set_token(value: str) -> None:
    """
    Legacy function: updates the default identity's token if it exists,
    otherwise falls back to old Token table.
    """
    identity = await get_default_identity()
    if identity and identity.config_name:
        set_credential(identity.config_name, "access_token", value)
        async with async_session() as session:
            stmt = select(MastodonIdentity).where(MastodonIdentity.id == identity.id)
            db_identity = (await session.execute(stmt)).scalar_one()
            db_identity.access_token = ""
            await session.commit()
    elif identity:
        async with async_session() as session:
            stmt = select(MastodonIdentity).where(MastodonIdentity.id == identity.id)
            db_identity = (await session.execute(stmt)).scalar_one()
            db_identity.access_token = value
            await session.commit()
    else:
        # Fall back to old token table
        async with async_session() as session:
            result = await session.execute(
                select(Token).where(Token.key == "mastodon_access_token")
            )
            token = result.scalar_one_or_none()
            if token:
                token.value = value
            else:
                session.add(Token(key="mastodon_access_token", value=value))
            await session.commit()


class SeenPost(Base):
    """
    Tracks which posts a specific MetaAccount has viewed.
    Scoped by meta_account_id so multiple users don't share read states.
    """

    __tablename__ = "seen_posts"

    post_id: Mapped[str] = mapped_column(String, primary_key=True)
    meta_account_id: Mapped[int] = mapped_column(
        ForeignKey("meta_accounts.id"), primary_key=True
    )
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (Index("ix_seen_lookup", "meta_account_id", "post_id"),)


async def mark_post_seen(meta_account_id: int, post_id: str) -> None:
    async with async_session() as session:
        stmt = select(SeenPost).where(
            SeenPost.meta_account_id == meta_account_id,
            SeenPost.post_id == post_id,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if not existing:
            session.add(SeenPost(meta_account_id=meta_account_id, post_id=post_id))
            await session.commit()


async def mark_posts_seen(meta_account_id: int, post_ids: list[str]) -> None:
    if not post_ids:
        return
    # Deduplicate to avoid redundant rows inside one statement
    unique_ids = list(dict.fromkeys(post_ids))
    rows = [{"meta_account_id": meta_account_id, "post_id": pid} for pid in unique_ids]
    async with async_session() as session:
        await session.execute(
            insert(SeenPost).values(rows).prefix_with("OR IGNORE")
        )
        await session.commit()


async def get_seen_posts(meta_account_id: int, post_ids: list[str]) -> set[str]:
    if not post_ids:
        return set()
    async with async_session() as session:
        stmt = select(SeenPost.post_id).where(
            SeenPost.meta_account_id == meta_account_id,
            SeenPost.post_id.in_(post_ids),
        )
        result = await session.execute(stmt)
        return set(row[0] for row in result.fetchall())


async def get_unread_count(meta_account_id: int, since: datetime | None = None) -> int:
    async with async_session() as session:
        stmt = select(func.count(SeenPost.post_id)).where(
            SeenPost.meta_account_id == meta_account_id
        )
        if since:
            stmt = stmt.where(SeenPost.seen_at >= since)
        return (await session.execute(stmt)).scalar_one()
