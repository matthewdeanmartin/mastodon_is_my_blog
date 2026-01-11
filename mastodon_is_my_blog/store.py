import os
from datetime import datetime
from typing import Optional

import dotenv
from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# logging.basicConfig()
# logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)

dotenv.load_dotenv()

DB_URL = os.environ.get("DB_URL", "sqlite+aiosqlite:///./app.db")
# Database setup
engine = create_async_engine(
    DB_URL,
    echo=False,
)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Token(Base):
    __tablename__ = "tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)
    value: Mapped[str] = mapped_column(String(500))


class CachedAccount(Base):
    """Stores friends, followers, and active posters for the Blog Roll"""

    __tablename__ = "cached_accounts"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # Mastodon ID
    acct: Mapped[str] = mapped_column(String, index=True)  # user@instance
    display_name: Mapped[str] = mapped_column(String)
    avatar: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    note: Mapped[str] = mapped_column(Text, default="")  # Bio/description

    # Relationship flags
    is_following: Mapped[bool] = mapped_column(Boolean, default=False)
    is_followed_by: Mapped[bool] = mapped_column(Boolean, default=False)

    # Activity tracking for Blog Roll
    last_status_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )  # Added index here for the blogroll sort


class CachedPost(Base):
    __tablename__ = "cached_posts"

    # Define Composite Indexes to speed up specific query patterns
    __table_args__ = (
        # 1. Main Feed: "Show me posts sorted by date"
        Index("ix_posts_created_at", "created_at"),
        # 2. User Profile: "Show me THIS user's posts, sorted by date"
        Index("ix_posts_author_created", "author_acct", "created_at"),
        # Covering indexes for COUNT queries (add columns used in WHERE)
        # These help avoid table lookups during counts
        Index(
            "ix_posts_storms_count",
            "is_reblog",
            "in_reply_to_id",
            "has_link",
            "author_acct",  # Added for user filtering
        ),
        # Optimized filter indexes with author for user-specific queries
        Index("ix_posts_news_author", "has_news", "author_acct", "created_at"),
        Index("ix_posts_tech_author", "has_tech", "author_acct", "created_at"),
        Index("ix_posts_media_author", "has_media", "author_acct", "created_at"),
        Index("ix_posts_video_author", "has_video", "author_acct", "created_at"),
        Index("ix_posts_links_author", "has_link", "author_acct", "created_at"),
        Index("ix_posts_questions_author", "has_question", "author_acct", "created_at"),
        Index("ix_posts_reply_author", "is_reply", "author_acct", "created_at"),
        # Compound index for "clean feed" queries (most common)
        Index(
            "ix_posts_clean_feed_optimized",
            "author_acct",
            "is_reblog",
            "is_reply",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)  # Mastodon ID
    content: Mapped[str] = mapped_column(Text)
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


class AppState(Base):
    __tablename__ = "app_state"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    last_sync: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# --- Token Helpers ---
async def get_token(key: str = "mastodon_access_token") -> Optional[str]:
    async with async_session() as session:
        result = await session.execute(select(Token).where(Token.key == key))
        token = result.scalar_one_or_none()
        return token.value if token else os.environ.get("MASTODON_ACCESS_TOKEN")


async def set_token(value: str) -> None:
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


# --- Sync State Logic ---
async def get_last_sync(key: str = "main_timeline") -> Optional[datetime]:
    async with async_session() as session:
        res = await session.execute(select(AppState).where(AppState.key == key))
        state = res.scalar_one_or_none()
        return state.last_sync if state else None


async def update_last_sync(key: str = "main_timeline") -> None:
    async with async_session() as session:
        res = await session.execute(select(AppState).where(AppState.key == key))
        state = res.scalar_one_or_none()
        if state:
            state.last_sync = datetime.utcnow()
        else:
            session.add(AppState(key=key, last_sync=datetime.utcnow()))
        await session.commit()
