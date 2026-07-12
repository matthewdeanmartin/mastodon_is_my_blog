"""Phase 1 of the Turso/Postgres plan (spec/turso_support_phases.md).

Covers backend resolution from env, backend-aware URL building, pragma/pool
gating, and that the dialect-portable upsert helpers emit the right construct
per dialect. All existing behavior on the default sqlite backend is preserved.
"""

from __future__ import annotations

import pytest

from mastodon_is_my_blog import db_path, dialect_upsert
from mastodon_is_my_blog.db_backend import (
    DatabaseBackend,
    backend_from_url,
    build_engine_kwargs,
    is_sqlite,
    resolve_backend,
    uses_sqlite_dialect,
)


@pytest.fixture(autouse=True)
def clean_backend_env(monkeypatch):
    """Each test controls the backend env explicitly."""
    for key in (
        "DB_BACKEND",
        "DB_URL",
        "APP_TURSO_URL",
        "APP_TURSO_AUTH_TOKEN",
        "APP_POSTGRES_URL",
        "APP_PG_HOST",
        "APP_PG_PORT",
        "APP_PG_USER",
        "APP_PG_PASSWORD",
        "APP_PG_DB",
    ):
        monkeypatch.delenv(key, raising=False)


# --- resolve_backend -------------------------------------------------------


def test_default_backend_is_sqlite():
    assert resolve_backend() == DatabaseBackend.SQLITE


@pytest.mark.parametrize(
    "value,expected",
    [
        ("sqlite", DatabaseBackend.SQLITE),
        ("turso", DatabaseBackend.TURSO),
        ("postgres", DatabaseBackend.POSTGRES),
        ("  Postgres  ", DatabaseBackend.POSTGRES),
    ],
)
def test_db_backend_env_wins(monkeypatch, value, expected):
    monkeypatch.setenv("DB_BACKEND", value)
    assert resolve_backend() == expected


def test_unknown_db_backend_raises(monkeypatch):
    monkeypatch.setenv("DB_BACKEND", "cassandra")
    with pytest.raises(ValueError, match="Unknown DB_BACKEND"):
        resolve_backend()


def test_backend_inferred_from_db_url_when_backend_unset(monkeypatch):
    monkeypatch.setenv("DB_URL", "postgresql+asyncpg://u@h/db")
    assert resolve_backend() == DatabaseBackend.POSTGRES


def test_db_url_scheme_overrides_stale_db_backend(monkeypatch):
    monkeypatch.setenv("DB_URL", "postgresql+asyncpg://u@h/db")
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    assert resolve_backend() == DatabaseBackend.POSTGRES


@pytest.mark.parametrize(
    "url,expected",
    [
        ("sqlite+aiosqlite:///app.db", DatabaseBackend.SQLITE),
        ("sqlite+libsql://db.turso.io", DatabaseBackend.TURSO),
        ("libsql://db.turso.io", DatabaseBackend.TURSO),
        ("postgresql+asyncpg://u@h/db", DatabaseBackend.POSTGRES),
        ("mysql://nope", None),
    ],
)
def test_backend_from_url(url, expected):
    assert backend_from_url(url) == expected


# --- gating helpers --------------------------------------------------------


def test_is_sqlite_only_true_for_sqlite():
    assert is_sqlite(DatabaseBackend.SQLITE)
    assert not is_sqlite(DatabaseBackend.TURSO)
    assert not is_sqlite(DatabaseBackend.POSTGRES)


def test_turso_uses_sqlite_dialect_but_is_not_sqlite():
    # libSQL speaks the sqlite dialect for SQL, but is not a local aiosqlite file.
    assert uses_sqlite_dialect(DatabaseBackend.TURSO)
    assert not is_sqlite(DatabaseBackend.TURSO)


def test_postgres_uses_postgres_dialect():
    assert not uses_sqlite_dialect(DatabaseBackend.POSTGRES)


def test_engine_kwargs_sqlite_has_no_pool_settings():
    assert build_engine_kwargs(DatabaseBackend.SQLITE) == {}


def test_engine_kwargs_server_backends_get_a_pool():
    for backend in (DatabaseBackend.TURSO, DatabaseBackend.POSTGRES):
        kwargs = build_engine_kwargs(backend)
        assert kwargs["pool_pre_ping"] is True
        assert kwargs["pool_size"] > 0


# --- URL building ----------------------------------------------------------


def test_db_url_override_wins(monkeypatch):
    monkeypatch.setenv("DB_URL", "sqlite+aiosqlite:///custom.db")
    assert db_path.get_default_db_url() == "sqlite+aiosqlite:///custom.db"


def test_sqlite_default_url_shape(monkeypatch):
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    url = db_path.get_default_db_url()
    assert url.startswith("sqlite+aiosqlite:///")
    assert url.endswith("app.db")


def test_turso_url_requires_config(monkeypatch):
    monkeypatch.setenv("DB_BACKEND", "turso")
    with pytest.raises(ValueError, match="APP_TURSO_URL"):
        db_path.get_default_db_url()


def test_turso_url_normalises_scheme_and_injects_token(monkeypatch):
    monkeypatch.setenv("DB_BACKEND", "turso")
    monkeypatch.setenv("APP_TURSO_URL", "libsql://db.turso.io")
    monkeypatch.setenv("APP_TURSO_AUTH_TOKEN", "secret-token")
    url = db_path.get_default_db_url()
    assert url.startswith("sqlite+libsql://db.turso.io")
    assert "authToken=secret-token" in url


def test_postgres_url_from_full_env(monkeypatch):
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setenv("APP_POSTGRES_URL", "postgresql://u:p@h:5432/mydb")
    url = db_path.get_default_db_url()
    assert url == "postgresql+asyncpg://u:p@h:5432/mydb"


def test_postgres_url_assembled_from_parts(monkeypatch):
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setenv("APP_PG_HOST", "dbhost")
    monkeypatch.setenv("APP_PG_USER", "alice")
    monkeypatch.setenv("APP_PG_PASSWORD", "pw")
    monkeypatch.setenv("APP_PG_DB", "blog")
    url = db_path.get_default_db_url()
    assert url == "postgresql+asyncpg://alice:pw@dbhost:5432/blog"


def test_sqlite_file_path_rejects_non_sqlite(monkeypatch):
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setenv("APP_POSTGRES_URL", "postgresql://u@h/db")
    with pytest.raises(ValueError, match="sqlite backend"):
        db_path.get_sqlite_file_path()


# --- dialect-portable upsert ----------------------------------------------


def _compile(stmt, dialect_name):
    if dialect_name == "sqlite":
        from sqlalchemy.dialects import sqlite as d

        dialect = d.dialect()
    else:
        from sqlalchemy.dialects import postgresql as d

        dialect = d.dialect()
    return str(stmt.compile(dialect=dialect))


def _seen_post_table():
    from mastodon_is_my_blog.store import SeenPost

    return SeenPost


def test_insert_or_ignore_emits_sqlite_on_conflict(monkeypatch):
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    SeenPost = _seen_post_table()
    stmt = dialect_upsert.insert_or_ignore(
        SeenPost,
        [{"meta_account_id": 1, "post_id": "p1"}],
        index_elements=["post_id", "meta_account_id"],
    )
    sql = _compile(stmt, "sqlite").upper()
    assert "ON CONFLICT" in sql
    assert "DO NOTHING" in sql


def test_insert_or_ignore_emits_postgres_on_conflict(monkeypatch):
    monkeypatch.setenv("DB_BACKEND", "postgres")
    SeenPost = _seen_post_table()
    stmt = dialect_upsert.insert_or_ignore(
        SeenPost,
        [{"meta_account_id": 1, "post_id": "p1"}],
        index_elements=["post_id", "meta_account_id"],
    )
    sql = _compile(stmt, "postgresql").upper()
    assert "ON CONFLICT" in sql
    assert "DO NOTHING" in sql


def test_dialect_insert_switches_with_backend(monkeypatch):
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    monkeypatch.setenv("DB_BACKEND", "sqlite")
    assert dialect_upsert.dialect_insert() is sqlite_insert

    monkeypatch.setenv("DB_BACKEND", "turso")
    assert dialect_upsert.dialect_insert() is sqlite_insert  # libsql -> sqlite dialect

    monkeypatch.setenv("DB_BACKEND", "postgres")
    assert dialect_upsert.dialect_insert() is pg_insert


def test_insert_with_conflict_update_sets_excluded_columns(monkeypatch):
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    SeenPost = _seen_post_table()
    stmt = dialect_upsert.insert_with_conflict_update(
        SeenPost,
        [{"meta_account_id": 1, "post_id": "p1", "seen_at": None}],
        index_elements=["post_id", "meta_account_id"],
        update_columns=["seen_at"],
    )
    sql = _compile(stmt, "sqlite").upper()
    assert "ON CONFLICT" in sql
    assert "DO UPDATE" in sql
    assert "SEEN_AT" in sql
