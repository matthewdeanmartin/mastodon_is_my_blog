from __future__ import annotations

# mastodon_is_my_blog/db_backend.py
"""
Backend selection for the storage engine.

Phase 1 of the Turso/Postgres plan (see spec/turso_support_phases.md): the whole
app is async SQLAlchemy, and libSQL (Turso) and Postgres both ship async
dialects, so the *same* models and session code can run on three backends. This
module is the single seam that decides which one.

The default is ``sqlite`` and existing ``DB_URL`` installs are unaffected — the
backend is inferred from the URL scheme when ``DB_BACKEND`` is not set.
"""

import os
from enum import StrEnum


class DatabaseBackend(StrEnum):
    SQLITE = "sqlite"
    TURSO = "turso"  # libSQL, via the sqlalchemy-libsql dialect
    POSTGRES = "postgres"  # via asyncpg


# URL scheme prefixes we recognise when inferring a backend from an explicit
# DB_URL (so a user who set DB_URL=postgresql+asyncpg://... need not also set
# DB_BACKEND).
SCHEME_TO_BACKEND: dict[str, DatabaseBackend] = {
    "sqlite+aiosqlite": DatabaseBackend.SQLITE,
    "sqlite": DatabaseBackend.SQLITE,
    "sqlite+libsql": DatabaseBackend.TURSO,
    "libsql": DatabaseBackend.TURSO,
    "postgresql+asyncpg": DatabaseBackend.POSTGRES,
    "postgresql": DatabaseBackend.POSTGRES,
    "postgres": DatabaseBackend.POSTGRES,
}


def backend_from_url(url: str) -> DatabaseBackend | None:
    """Infer the backend from a SQLAlchemy URL scheme, or None if unrecognised."""
    scheme = url.split(":", 1)[0].strip().lower()
    return SCHEME_TO_BACKEND.get(scheme)


def resolve_backend() -> DatabaseBackend:
    """
    Decide the active backend.

    Precedence:
      1. Inferred from an explicit ``DB_URL`` scheme.
      2. ``DB_BACKEND`` env var (sqlite | turso | postgres), if set.
      3. Default: sqlite.

    DB_URL is authoritative when present so a stale DB_BACKEND cannot make the
    engine and its backend-specific setup disagree.
    """
    if db_url := os.environ.get("DB_URL"):
        if inferred := backend_from_url(db_url):
            return inferred

    raw = os.environ.get("DB_BACKEND")
    if raw:
        try:
            return DatabaseBackend(raw.strip().lower())
        except ValueError as exc:
            valid = ", ".join(b.value for b in DatabaseBackend)
            raise ValueError(f"Unknown DB_BACKEND={raw!r}. Valid values: {valid}.") from exc

    return DatabaseBackend.SQLITE


def is_sqlite(backend: DatabaseBackend) -> bool:
    """
    True for the classic SQLite (aiosqlite) backend only.

    Turso/libSQL uses the sqlite *dialect* for SQL generation but is NOT this:
    file-level PRAGMAs (journal_mode=WAL, mmap_size, ...) and the DuckDB
    sqlite_scanner attach only make sense for a local aiosqlite file.
    """
    return backend == DatabaseBackend.SQLITE


def uses_sqlite_dialect(backend: DatabaseBackend) -> bool:
    """
    True when SQLAlchemy speaks the SQLite dialect for this backend — sqlite AND
    turso/libSQL. Used to pick ``INSERT ... ON CONFLICT`` construct flavour.
    """
    return backend in (DatabaseBackend.SQLITE, DatabaseBackend.TURSO)


def build_engine_kwargs(backend: DatabaseBackend) -> dict:
    """
    Per-backend ``create_async_engine`` keyword arguments.

    sqlite/aiosqlite: leave pooling to SQLAlchemy's default (a single file, and
    the WAL pragmas do the concurrency heavy lifting).

    turso/postgres: real client/server connections, so use a modest connection
    pool with pre-ping to survive idle drops. These are the backends that
    actually relieve the write-serialization slowness of local SQLite.
    """
    if is_sqlite(backend):
        return {}
    return {
        "pool_size": 5,
        "max_overflow": 10,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }
