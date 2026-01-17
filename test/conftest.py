# tests/conftest.py
import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

# 1. Setup Test DB Engine
# We use StaticPool so the in-memory DB persists across multiple connections
# within the same test session.
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

from mastodon_is_my_blog.main import app
from mastodon_is_my_blog.store import Base, get_token

# Create a test engine (single threaded for memory DB)
test_engine = create_async_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)

# Import dependencies AFTER defining the engine to avoid early init issues
from mastodon_is_my_blog import main, store
from mastodon_is_my_blog.store import Base

@pytest_asyncio.fixture(scope="function")
async def db_session():
    """
    Creates a fresh in-memory database for each test function.
    """
    # Create tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Return a session
    async with TestingSessionLocal() as session:
        yield session

    # Drop tables (cleanup)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    """
    Returns a FastAPI AsyncClient, overriding the DB dependency
    if you were using `Depends(get_db)`.

    Since your app imports `async_session` directly in main.py,
    we must patch the `mastodon_is_my_blog.store.async_session`
    to point to our test session maker.
    """
    # SAVE ORIGINAL REFS
    original_main_session = main.async_session
    original_store_session = store.async_session

    # PATCH REFS
    # We must patch 'main.async_session' because main.py did:
    # "from mastodon_is_my_blog.store import async_session"
    main.async_session = TestingSessionLocal
    store.async_session = TestingSessionLocal

    # Create client
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # RESTORE REFS
    main.async_session = original_main_session
    store.async_session = original_store_session