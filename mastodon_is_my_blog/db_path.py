from __future__ import annotations

import os
from pathlib import Path

from mastodon_is_my_blog.db_backend import DatabaseBackend, resolve_backend


def _turso_url() -> str:
    """
    Build a libSQL/Turso async URL from env.

    APP_TURSO_URL   e.g. libsql://your-db.turso.io  (or a full
                    sqlite+libsql://... URL, used as-is)
    keyring / APP_TURSO_AUTH_TOKEN  auth token (env checked first; keyring is
                    the recommended store per turso_support.md §13).
    """
    url = os.environ.get("APP_TURSO_URL")
    if not url:
        raise ValueError("DB_BACKEND=turso requires APP_TURSO_URL (e.g. libsql://your-db.turso.io).")
    if not url.startswith("sqlite+libsql://"):
        # normalise libsql://host -> sqlite+libsql://host for the dialect
        host = url.split("://", 1)[-1]
        url = f"sqlite+libsql://{host}"

    token = os.environ.get("APP_TURSO_AUTH_TOKEN")
    if not token:
        try:
            import keyring

            token = keyring.get_password("mastodon_is_my_blog", "turso-auth-token")
        except Exception:
            token = None
    if token and "authToken=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}authToken={token}"
    return url


def _postgres_url() -> str:
    """
    Build a Postgres async (asyncpg) URL from env.

    APP_POSTGRES_URL  full URL wins if given (scheme normalised to
                      postgresql+asyncpg://). Otherwise assembled from
                      APP_PG_HOST/PORT/USER/PASSWORD/DB.
    """
    if url := os.environ.get("APP_POSTGRES_URL"):
        for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+asyncpg://" + url[len(prefix) :]
        return url

    host = os.environ.get("APP_PG_HOST", "localhost")
    port = os.environ.get("APP_PG_PORT", "5432")
    user = os.environ.get("APP_PG_USER", "postgres")
    password = os.environ.get("APP_PG_PASSWORD", "")
    db = os.environ.get("APP_PG_DB", "mastodon_is_my_blog")
    auth = f"{user}:{password}" if password else user
    return f"postgresql+asyncpg://{auth}@{host}:{port}/{db}"


def get_default_db_url() -> str:
    """
    Return a SQLAlchemy-compatible async URL for the active backend.

    ``DB_URL`` still wins unconditionally (existing installs unaffected).
    Otherwise the URL is built from the resolved backend:
      sqlite   -> sqlite+aiosqlite:///<user data dir>/app.db  (unchanged default)
      turso    -> sqlite+libsql://...  (see APP_TURSO_URL / auth token)
      postgres -> postgresql+asyncpg://...  (see APP_POSTGRES_URL / APP_PG_*)
    """
    if db_url := os.environ.get("DB_URL"):
        return db_url

    backend = resolve_backend()
    if backend == DatabaseBackend.TURSO:
        return _turso_url()
    if backend == DatabaseBackend.POSTGRES:
        return _postgres_url()

    # Default: local SQLite file (unchanged behavior).
    from platformdirs import user_data_dir

    data_dir = Path(user_data_dir(appname="mastodon_is_my_blog", appauthor=False))
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "app.db"
    return f"sqlite+aiosqlite:///{db_path}"


def get_sqlite_file_path() -> str:
    """
    Return the filesystem path to the SQLite database.
    Strips the SQLAlchemy ``sqlite+aiosqlite:///`` or ``sqlite:///`` prefix
    from whatever ``get_default_db_url`` returns. Used by DuckDB's
    ``sqlite_scanner`` which wants a bare path, not a SQLAlchemy URL.

    Only valid on the SQLite backend — DuckDB-based analytics attach to the
    local file directly and have no equivalent on turso/postgres.
    """
    url = get_default_db_url()
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return url[len(prefix) :]
    raise ValueError(f"DuckDB analytics require the sqlite backend (it attaches the local database file directly). Active DB URL is not sqlite: {url!r}.")
