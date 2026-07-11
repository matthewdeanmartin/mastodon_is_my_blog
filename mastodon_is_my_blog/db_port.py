from __future__ import annotations

# mastodon_is_my_blog/db_port.py
"""
Backend-agnostic two-way database port: export/import/port/diff/verify.

This is the migration path between backends (SQLite <-> Turso <-> Postgres) and
the debuggable backup format (turso_support_phases.md Phase 3, turso_support.md
§9-§16). Everything goes through SQLAlchemy Core against ``Base.metadata``, so it
works on every backend and stays in sync with the models automatically.

Format: JSONL, one ``{"table": ..., "row": {...}}`` object per line. Tables are
emitted in ``Base.metadata.sorted_tables`` order (FK-safe: parents before
children) so a straight replay imports cleanly.

Datetime columns are stored naive-UTC in this app (see datetime_helpers); they
serialize to ISO-8601 strings and are coerced back to naive datetimes on import
using each column's SQLAlchemy type.
"""

import hashlib
import json
import logging
from collections.abc import AsyncIterator, Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Table, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mastodon_is_my_blog.db_path import get_default_db_url
from mastodon_is_my_blog.dialect_upsert import dialect_insert
from mastodon_is_my_blog.store import Base

logger = logging.getLogger(__name__)

IMPORT_MODES = ("insert-only", "upsert-newer", "fail-on-conflict")
DEFAULT_MODE = "upsert-newer"


# --- engine helpers --------------------------------------------------------


def _engine_for(url: str | None) -> AsyncEngine:
    """An engine for an explicit URL, or the app's active backend if None."""
    return create_async_engine(url or get_default_db_url())


def _sorted_tables() -> list[Table]:
    return list(Base.metadata.sorted_tables)


def _table_by_name(name: str) -> Table | None:
    return Base.metadata.tables.get(name)


# --- (de)serialization -----------------------------------------------------


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return {"__bytes__": value.hex()}
    raise TypeError(f"Cannot serialize {type(value).__name__} to JSON")


def _row_to_jsonable(row: dict[str, Any]) -> dict[str, Any]:
    return row


def _coerce_imported_row(table: Table, row: dict[str, Any]) -> dict[str, Any]:
    """Turn JSON-decoded scalars back into the column's Python type."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        col = table.columns.get(key)
        if col is None:
            out[key] = value
            continue
        if value is not None and isinstance(col.type, DateTime):
            if isinstance(value, str):
                parsed = datetime.fromisoformat(value)
                # this app stores naive UTC
                out[key] = parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
                continue
        if isinstance(value, dict) and "__bytes__" in value:
            out[key] = bytes.fromhex(value["__bytes__"])
            continue
        out[key] = value
    return out


# --- content hashing (verify) ---------------------------------------------


def row_hash(row: dict[str, Any]) -> str:
    """Stable content hash of a row (turso_support.md §16).

    Excludes ``content_hash`` itself if present; datetimes -> ISO strings so the
    hash is backend-independent.
    """
    stable = {key: (row[key].isoformat() if isinstance(row[key], (datetime, date)) else row[key]) for key in sorted(row) if key != "content_hash"}
    payload = json.dumps(stable, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- reading ---------------------------------------------------------------


async def _iter_rows(engine: AsyncEngine, table: Table) -> AsyncIterator[dict[str, Any]]:
    async with engine.connect() as conn:
        result = await conn.stream(select(table))
        async for row in result.mappings():
            yield dict(row)


async def count_rows(engine: AsyncEngine, table: Table) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(select(func.count()).select_from(table))
        return int(result.scalar_one())


# --- export ----------------------------------------------------------------


async def export_jsonl(out_path: Path, *, url: str | None = None) -> dict[str, int]:
    """Export every model table to JSONL. Returns per-table row counts."""
    engine = _engine_for(url)
    counts: dict[str, int] = {}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with out_path.open("w", encoding="utf-8") as handle:
            for table in _sorted_tables():
                n = 0
                async for row in _iter_rows(engine, table):
                    handle.write(
                        json.dumps(
                            {"table": table.name, "row": _row_to_jsonable(row)},
                            default=_json_default,
                        )
                    )
                    handle.write("\n")
                    n += 1
                counts[table.name] = n
    finally:
        await engine.dispose()
    logger.info("Exported %d tables to %s", len(counts), out_path)
    return counts


# --- import ----------------------------------------------------------------


def _read_jsonl(in_path: Path) -> Iterable[tuple[str, dict[str, Any]]]:
    with in_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            yield obj["table"], obj["row"]


async def _table_is_empty(engine: AsyncEngine, table: Table) -> bool:
    return (await count_rows(engine, table)) == 0


async def import_jsonl(
    in_path: Path,
    *,
    url: str | None = None,
    mode: str = DEFAULT_MODE,
    force: bool = False,
) -> dict[str, int]:
    """
    Import JSONL into the target backend.

    Modes (turso_support.md §9):
      insert-only      -- skip rows whose PK already exists.
      upsert-newer     -- insert new rows; overwrite existing rows (last-writer;
                          the app's tables carry no revision column yet, so this
                          is a straight upsert on PK).
      fail-on-conflict -- refuse if any incoming PK already exists.

    Guard: importing into a non-empty DB requires ``force=True`` unless the mode
    is upsert-newer (turso_support.md §17).
    """
    if mode not in IMPORT_MODES:
        raise ValueError(f"Unknown import mode {mode!r}. Valid: {', '.join(IMPORT_MODES)}")

    engine = _engine_for(url)
    written: dict[str, int] = {}
    try:
        # Destructive-import guard.
        if mode != "upsert-newer" and not force:
            for table in _sorted_tables():
                if not await _table_is_empty(engine, table):
                    raise RuntimeError(f"Refusing to import into non-empty database without --mode upsert-newer or --force (table {table.name!r} is not empty).")

        # Group rows by table, preserving file order.
        rows_by_table: dict[str, list[dict[str, Any]]] = {}
        for table_name, row in _read_jsonl(in_path):
            rows_by_table.setdefault(table_name, []).append(row)

        for table in _sorted_tables():
            rows = rows_by_table.get(table.name)
            if not rows:
                continue
            coerced = [_coerce_imported_row(table, r) for r in rows]
            written[table.name] = await _apply_rows(engine, table, coerced, mode)
    finally:
        await engine.dispose()
    logger.info("Imported into %d tables from %s (mode=%s)", len(written), in_path, mode)
    return written


def _pk_columns(table: Table) -> list[str]:
    return [c.name for c in table.primary_key.columns]


async def _existing_pks(engine: AsyncEngine, table: Table, rows: list[dict[str, Any]]) -> set[tuple]:
    pk_cols = _pk_columns(table)
    if not pk_cols:
        return set()
    async with engine.connect() as conn:
        result = await conn.execute(select(*[table.c[c] for c in pk_cols]))
        return {tuple(r) for r in result.all()}


def _chunk_size(table: Table) -> int:
    """Rows per INSERT so total bind params stay well under driver limits.

    asyncpg caps a statement at 32767 params; a multi-VALUES ``ON CONFLICT``
    statement uses (#columns * #rows) params. Keep a safe margin.
    """
    ncols = max(1, len(table.columns))
    return max(1, min(1000, 30000 // ncols))


def _chunked(rows: list[dict[str, Any]], size: int):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


async def _apply_rows(engine: AsyncEngine, table: Table, rows: list[dict[str, Any]], mode: str) -> int:
    pk_cols = _pk_columns(table)
    size = _chunk_size(table)

    if mode == "fail-on-conflict":
        existing = await _existing_pks(engine, table, rows)
        for r in rows:
            key = tuple(r.get(c) for c in pk_cols)
            if key in existing:
                raise RuntimeError(f"Conflict: {table.name} row with PK {key} already exists.")
        async with engine.begin() as conn:
            # executemany-style: driver handles batching, no VALUES-list cap.
            await conn.execute(table.insert(), rows)
        return len(rows)

    update_cols = [c.name for c in table.columns if c.name not in pk_cols]

    async with engine.begin() as conn:
        for batch in _chunked(rows, size):
            insert = dialect_insert()
            stmt = insert(table).values(batch)
            if mode == "insert-only":
                stmt = stmt.on_conflict_do_nothing()
            elif update_cols:  # upsert-newer
                stmt = stmt.on_conflict_do_update(
                    index_elements=pk_cols,
                    set_={c: stmt.excluded[c] for c in update_cols},
                )
            else:
                stmt = stmt.on_conflict_do_nothing()
            await conn.execute(stmt)
    return len(rows)


# --- port (export -> import in one shot) -----------------------------------


async def port(
    *,
    from_url: str,
    to_url: str,
    tmp_path: Path,
    mode: str = DEFAULT_MODE,
    force: bool = False,
) -> dict[str, Any]:
    """Copy every table from one backend to another via a JSONL intermediate."""
    exported = await export_jsonl(tmp_path, url=from_url)
    written = await import_jsonl(tmp_path, url=to_url, mode=mode, force=force)
    return {"exported": exported, "written": written}


async def port_direct(
    *,
    from_url: str,
    to_url: str,
    mode: str = DEFAULT_MODE,
    force: bool = False,
    skip_tables: tuple[str, ...] = (),
    defer_fk_checks: bool = True,
    progress: Any = None,
) -> dict[str, int]:
    """
    Stream every table source -> target directly, one chunk at a time.

    Unlike ``port``, this holds no full-table dict and writes no intermediate
    file — required for large tables (e.g. 700k+ rows) where the JSONL path
    would exhaust memory. Rows are coerced through each column's type on the way
    in, same as ``import_jsonl``.

    ``defer_fk_checks`` disables target FK enforcement during the load (Postgres
    superuser only) so orphaned rows tolerated by SQLite copy over faithfully.
    Note: ``session_replication_role`` is per-session, so each ``engine.begin()``
    block re-applies it; enforcement is toggled per chunk write below.
    """
    from sqlalchemy import text

    source = _engine_for(from_url)
    target = _engine_for(to_url)
    written: dict[str, int] = {}
    # session_replication_role is reset when a pooled connection returns to the
    # pool, so pin ONE target connection for the whole load and drive an explicit
    # transaction on it.
    try:
        if mode != "upsert-newer" and not force:
            for table in _sorted_tables():
                if table.name in skip_tables:
                    continue
                if not await _table_is_empty(target, table):
                    raise RuntimeError(f"Refusing to import into non-empty database without upsert-newer or force (table {table.name!r} not empty).")

        async with target.connect() as tconn:
            is_pg = target.dialect.name == "postgresql"
            if defer_fk_checks and is_pg:
                try:
                    await tconn.execute(text("SET session_replication_role = replica"))
                except Exception:
                    pass  # not a superuser; FK checks stay on

            for table in _sorted_tables():
                if table.name in skip_tables:
                    continue
                size = _chunk_size(table)
                buffer: list[dict[str, Any]] = []
                n = 0
                async for row in _iter_rows(source, table):
                    buffer.append(_coerce_imported_row(table, row))
                    if len(buffer) >= size:
                        await _apply_rows_conn(tconn, table, buffer, mode)
                        n += len(buffer)
                        buffer = []
                if buffer:
                    await _apply_rows_conn(tconn, table, buffer, mode)
                    n += len(buffer)
                await tconn.commit()
                written[table.name] = n
                if progress is not None:
                    progress(table.name, n)

            if defer_fk_checks and is_pg:
                try:
                    await tconn.execute(text("SET session_replication_role = origin"))
                    await tconn.commit()
                except Exception:
                    pass
    finally:
        await source.dispose()
        await target.dispose()
    return written


async def _apply_rows_conn(conn, table: Table, rows: list[dict[str, Any]], mode: str) -> int:
    """Chunked upsert against an already-open connection (used by port_direct)."""
    pk_cols = _pk_columns(table)
    size = _chunk_size(table)
    update_cols = [c.name for c in table.columns if c.name not in pk_cols]
    for batch in _chunked(rows, size):
        if mode == "fail-on-conflict":
            await conn.execute(table.insert(), batch)
            continue
        insert = dialect_insert()
        stmt = insert(table).values(batch)
        if mode == "insert-only":
            stmt = stmt.on_conflict_do_nothing()
        elif update_cols:
            stmt = stmt.on_conflict_do_update(
                index_elements=pk_cols,
                set_={c: stmt.excluded[c] for c in update_cols},
            )
        else:
            stmt = stmt.on_conflict_do_nothing()
        await conn.execute(stmt)
    return len(rows)


# --- diff / verify ---------------------------------------------------------


async def _table_digest(engine: AsyncEngine, table: Table) -> tuple[int, str]:
    """Row count + combined content hash for one table (order-independent)."""
    hashes: list[str] = []
    async for row in _iter_rows(engine, table):
        hashes.append(row_hash(row))
    hashes.sort()
    combined = hashlib.sha256("".join(hashes).encode("utf-8")).hexdigest()
    return len(hashes), combined


async def verify(left_url: str | None, right_url: str | None) -> list[dict[str, Any]]:
    """
    Compare two databases table-by-table: row counts + content-hash match
    (turso_support.md §16). Returns a report row per table.
    """
    left = _engine_for(left_url)
    right = _engine_for(right_url)
    report: list[dict[str, Any]] = []
    try:
        for table in _sorted_tables():
            left_count, left_hash = await _table_digest(left, table)
            right_count, right_hash = await _table_digest(right, table)
            report.append(
                {
                    "table": table.name,
                    "left_rows": left_count,
                    "right_rows": right_count,
                    "hash_match": left_hash == right_hash,
                }
            )
    finally:
        await left.dispose()
        await right.dispose()
    return report


async def diff(left_url: str | None, right_url: str | None) -> list[dict[str, Any]]:
    """Like verify, but only the tables that differ."""
    full = await verify(left_url, right_url)
    return [r for r in full if r["left_rows"] != r["right_rows"] or not r["hash_match"]]


def format_verify_report(report: list[dict[str, Any]]) -> str:
    """Render a verify/diff report as an aligned text table."""
    header = f"{'Table':<28}{'Left':>8}{'Right':>8}  {'Hash match':<10}"
    lines = [header, "-" * len(header)]
    for r in report:
        match = "yes" if r["hash_match"] else "NO"
        lines.append(f"{r['table']:<28}{r['left_rows']:>8}{r['right_rows']:>8}  {match:<10}")
    return "\n".join(lines)
