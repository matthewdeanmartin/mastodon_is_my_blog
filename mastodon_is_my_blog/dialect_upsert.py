from __future__ import annotations

# mastodon_is_my_blog/dialect_upsert.py
"""
Dialect-portable ``INSERT ... ON CONFLICT`` helpers.

The app upserts with ``sqlalchemy.dialects.sqlite.insert(...).on_conflict_do_update``
and ``.prefix_with("OR IGNORE")``. Those are sqlite-dialect constructs — but
Postgres has the *same* ``on_conflict_do_update`` / ``on_conflict_do_nothing``
API in its dialect, and libSQL/Turso uses the sqlite dialect. These helpers pick
the right construct so upsert call sites stay backend-agnostic.

See spec/turso_support_phases.md (Phase 1).
"""

from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from mastodon_is_my_blog.db_backend import resolve_backend, uses_sqlite_dialect


def dialect_insert():
    """
    Return the dialect ``insert()`` constructor for the active backend.

    The returned constructor's statement exposes ``.excluded`` and
    ``.on_conflict_do_update`` / ``.on_conflict_do_nothing`` identically on the
    sqlite and postgres dialects, so call sites that build their SET clause
    inline (e.g. conditional column sets) can use this directly.
    """
    if uses_sqlite_dialect(resolve_backend()):
        return sqlite_insert
    return pg_insert


# Back-compat internal alias.
_insert_for_active_backend = dialect_insert


def insert_with_conflict_update(
    table: Any,
    values: Any,
    *,
    index_elements: list[str],
    update_columns: list[str],
):
    """
    Build an ``INSERT ... ON CONFLICT (index_elements) DO UPDATE`` statement whose
    SET clause copies ``update_columns`` from the excluded/proposed row.

    Works identically on the sqlite and postgres dialects (both expose
    ``on_conflict_do_update`` and an ``.excluded`` namespace).
    """
    insert = _insert_for_active_backend()
    stmt = insert(table).values(values)
    set_ = {col: stmt.excluded[col] for col in update_columns}
    return stmt.on_conflict_do_update(index_elements=index_elements, set_=set_)


def insert_or_ignore(table: Any, values: Any, *, index_elements: list[str] | None = None):
    """
    Portable ``INSERT OR IGNORE`` — skip rows that would violate a unique/PK
    constraint.

    sqlite/libsql: ``.on_conflict_do_nothing()`` (equivalent to the old
    ``prefix_with("OR IGNORE")`` but not dialect-locked).
    postgres: ``.on_conflict_do_nothing(index_elements=...)``.
    """
    insert = _insert_for_active_backend()
    stmt = insert(table).values(values)
    if index_elements is not None:
        return stmt.on_conflict_do_nothing(index_elements=index_elements)
    return stmt.on_conflict_do_nothing()
