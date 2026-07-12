from __future__ import annotations

# mastodon_is_my_blog/schema_version.py
"""
Report the active database backend, location, and Alembic schema version.

Used for the startup banner (spec/turso_support_phases.md Phase 2, §17 of
turso_support.md) and the ``db-info`` CLI command. Works on every backend —
the schema version is read from Alembic's ``alembic_version`` table, which
exists identically on sqlite/turso/postgres.
"""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from mastodon_is_my_blog.db_backend import DatabaseBackend
from mastodon_is_my_blog.store import DB_BACKEND, DB_URL, engine

logger = logging.getLogger(__name__)


def _redact(url: str) -> str:
    """Hide any password / authToken in a URL before printing or logging it."""
    redacted = url
    if "@" in redacted and "://" in redacted:
        scheme, rest = redacted.split("://", 1)
        if "@" in rest:
            creds, host = rest.split("@", 1)
            if ":" in creds:
                user = creds.split(":", 1)[0]
                creds = f"{user}:***"
            redacted = f"{scheme}://{creds}@{host}"
    if "authToken=" in redacted:
        head, _ = redacted.split("authToken=", 1)
        redacted = f"{head}authToken=***"
    return redacted


async def get_schema_version(db_engine: AsyncEngine | None = None) -> str | None:
    """Return the current Alembic revision, or None if unversioned/absent."""
    db_engine = db_engine or engine
    try:
        async with db_engine.connect() as conn:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            row = result.first()
            return row[0] if row else None
    except Exception:
        # No alembic_version table (e.g. a create_all-only local DB) — not an error.
        return None


async def describe_database(db_engine: AsyncEngine | None = None) -> dict[str, str]:
    """Structured backend/location/version info for banners and db-info."""
    version = await get_schema_version(db_engine)
    return {
        "backend": DB_BACKEND.value,
        "url": _redact(DB_URL),
        "schema_version": version or "unversioned (create_all)",
        "remote_sync": ("configured" if DB_BACKEND == DatabaseBackend.TURSO else "n/a"),
    }


async def log_startup_banner() -> None:
    """Emit the 'Database backend / location / schema version' startup banner."""
    info = await describe_database()
    logger.info("Database backend: %s", info["backend"])
    logger.info("Database URL: %s", info["url"])
    logger.info("Schema version: %s", info["schema_version"])
    async with engine.connect() as conn:
        posts_table = await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table("cached_posts"))
        accounts_table = await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table("cached_accounts"))
        post_count = await conn.scalar(text("SELECT count(*) FROM cached_posts")) if posts_table else 0
        account_count = await conn.scalar(text("SELECT count(*) FROM cached_accounts")) if accounts_table else 0
    logger.info("Existing data: %s posts, %s accounts", f"{post_count:,}", f"{account_count:,}")
    if post_count == 0 and account_count == 0:
        logger.warning("The selected database contains no cached application data")
    if info["remote_sync"] != "n/a":
        logger.info("Remote sync: %s", info["remote_sync"])
