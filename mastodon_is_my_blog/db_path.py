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
