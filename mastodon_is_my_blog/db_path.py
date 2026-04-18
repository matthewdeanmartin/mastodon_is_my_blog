from __future__ import annotations
import os
from pathlib import Path


def get_default_db_url() -> str:
    """
    Return a SQLAlchemy-compatible async URL for the SQLite database.
    If DB_URL is set in the environment, return it unchanged.
    Otherwise, resolve a user-specific path via platformdirs.
    """
    if db_url := os.environ.get("DB_URL"):
        return db_url

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
    """
    url = get_default_db_url()
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return url[len(prefix):]
    raise ValueError(f"Unsupported DB_URL for DuckDB attach: {url!r}")
