from __future__ import annotations

# mastodon_is_my_blog/db_init.py
"""
Fresh-vs-existing database initialization that works on every backend.

Reality of this repo's Alembic history: ``Base.metadata.create_all`` builds the
full current schema — tables AND every index defined on the models — so the
historical migrations (which *add* those same indexes incrementally) collide if
replayed against a create_all'd database. The migration chain is therefore only
meaningful for evolving an *already-provisioned* DB, not for building one from
empty.

So the correct provisioning path — and the one that lets turso/postgres come up
without the sqlite-only startup shims — is:

  * Fresh DB (no ``alembic_version`` row): ``create_all`` then ``stamp head``.
  * Existing DB already at some revision: leave it; run ``alembic upgrade`` by
    hand to advance it.

``init_db`` (store.py) still runs ``create_all`` at startup for backwards
compatibility; ``ensure_schema_stamped`` records the head so future
``alembic upgrade`` runs are correct.

See spec/turso_support_phases.md (Phase 2).
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy.ext.asyncio import AsyncEngine

from mastodon_is_my_blog.store import DB_URL, engine

logger = logging.getLogger(__name__)


def _alembic_config() -> Config:
    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DB_URL)
    return cfg


def _head_revision(cfg: Config) -> str | None:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(cfg)
    return script.get_current_head()


def _current_revision_sync(connection) -> str | None:
    context = MigrationContext.configure(connection)
    return context.get_current_revision()


async def current_revision(db_engine: AsyncEngine | None = None) -> str | None:
    """The DB's current Alembic revision, or None if unstamped."""
    db_engine = db_engine or engine
    async with db_engine.connect() as conn:
        return await conn.run_sync(_current_revision_sync)


async def ensure_schema_stamped(db_engine: AsyncEngine | None = None) -> str | None:
    """
    Stamp a freshly create_all'd DB at the Alembic head so later
    ``alembic upgrade`` calls behave. No-op if the DB is already stamped.

    Returns the revision the DB is at afterwards.
    """
    db_engine = db_engine or engine
    existing = await current_revision(db_engine)
    if existing is not None:
        return existing

    cfg = _alembic_config()
    head = _head_revision(cfg)
    if head is None:
        return None

    def _stamp(connection) -> None:
        cfg.attributes["connection"] = connection
        command.stamp(cfg, head)

    async with db_engine.begin() as conn:
        await conn.run_sync(_stamp)
    logger.info("Stamped fresh database at Alembic revision %s", head)
    return head
