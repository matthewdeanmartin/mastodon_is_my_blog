import os
from typing import Optional
from datetime import datetime, timedelta

import dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Text, Boolean, DateTime, select, delete

dotenv.load_dotenv()


# Database setup
engine = create_async_engine(
    os.environ.get("DB_URL", "sqlite+aiosqlite:///./app.db"),
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


class CachedPost(Base):
    __tablename__ = "cached_posts"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # Mastodon ID
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    visibility: Mapped[str] = mapped_column(String(20))

    # Metadata for filtering
    author_acct: Mapped[str] = mapped_column(String)
    is_reblog: Mapped[bool] = mapped_column(Boolean, default=False)
    is_reply: Mapped[bool] = mapped_column(Boolean, default=False)  # Track replies to others
    has_media: Mapped[bool] = mapped_column(Boolean, default=False)  # Images
    has_video: Mapped[bool] = mapped_column(Boolean, default=False)  # Youtube or video attachment

    # Store media attachments as JSON string
    media_attachments: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Comments/Context
    replies_count: Mapped[int] = mapped_column(Integer, default=0)


class AppState(Base):
    __tablename__ = "app_state"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    last_sync: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# --- Token Helpers (Existing) ---
async def get_token(key: str = "mastodon_access_token") -> Optional[str]:
    async with async_session() as session:
        result = await session.execute(select(Token).where(Token.key == key))
        token = result.scalar_one_or_none()
        return token.value if token else os.environ.get("MASTODON_ACCESS_TOKEN")


async def set_token(value: str) -> None:
    async with async_session() as session:
        result = await session.execute(select(Token).where(Token.key == "mastodon_access_token"))
        token = result.scalar_one_or_none()
        if token:
            token.value = value
        else:
            session.add(Token(key="mastodon_access_token", value=value))
        await session.commit()


# --- Sync Logic ---
async def get_last_sync() -> Optional[datetime]:
    async with async_session() as session:
        res = await session.execute(select(AppState).where(AppState.key == "main_timeline"))
        state = res.scalar_one_or_none()
        return state.last_sync if state else None


async def update_last_sync() -> None:
    async with async_session() as session:
        res = await session.execute(select(AppState).where(AppState.key == "main_timeline"))
        state = res.scalar_one_or_none()
        if state:
            state.last_sync = datetime.utcnow()
        else:
            session.add(AppState(key="main_timeline", last_sync=datetime.utcnow()))
        await session.commit()