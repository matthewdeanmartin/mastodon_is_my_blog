from __future__ import annotations

import pytest

from mastodon_is_my_blog.dev_database import require_postgres_url


def test_dev_database_requires_db_url() -> None:
    with pytest.raises(SystemExit, match="requires DB_URL"):
        require_postgres_url(None)


@pytest.mark.parametrize(
    "db_url",
    [
        "sqlite+aiosqlite:///app.db",
        "sqlite:///app.db",
    ],
)
def test_dev_database_rejects_sqlite(db_url: str) -> None:
    with pytest.raises(SystemExit, match="requires Postgres"):
        require_postgres_url(db_url)


def test_dev_database_normalizes_postgres_driver() -> None:
    result = require_postgres_url("postgresql://user:password@localhost:5432/mimb")
    assert result == "postgresql+asyncpg://user:password@localhost:5432/mimb"


def test_dev_database_preserves_asyncpg_url() -> None:
    db_url = "postgresql+asyncpg://user:password@localhost:5432/mimb"
    assert require_postgres_url(db_url) == db_url
