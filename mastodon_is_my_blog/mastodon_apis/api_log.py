"""
Synchronous, thread-safe writer for api_call_log.

Uses a raw sqlite3 connection (not SQLAlchemy) so it can be called safely from
synchronous code running inside asyncio.to_thread without touching the async
engine or event loop.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time

from mastodon_is_my_blog.db_backend import is_sqlite, resolve_backend
from mastodon_is_my_blog.db_path import get_sqlite_file_path

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
RETENTION_DAYS = 90


def get_connection() -> sqlite3.Connection | None:
    """Raw sqlite3 connection to api_call_log, or None off the sqlite backend
    (sqlite-only telemetry; no-ops on postgres/turso)."""
    global _conn
    if not is_sqlite(resolve_backend()):
        return None
    if _conn is None:
        path = get_sqlite_file_path()
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
    return _conn


def log_api_call(
    *,
    method_name: str,
    identity_acct: str | None,
    elapsed_s: float,
    payload_bytes: int,
    ok: bool,
    throttled: bool,
    error_type: str | None,
) -> None:
    try:
        with _lock:
            con = get_connection()
            if con is None:
                return  # non-sqlite backend: api_call_log is sqlite-only
            con.execute(
                """
                INSERT INTO api_call_log
                    (ts, method_name, identity_acct, elapsed_s, payload_bytes, ok, throttled, error_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    method_name,
                    identity_acct,
                    elapsed_s,
                    payload_bytes,
                    1 if ok else 0,
                    1 if throttled else 0,
                    error_type,
                ),
            )
            con.commit()
    except Exception:
        logger.exception("Failed to write api_call_log row (non-fatal)")


def purge_old_rows() -> int:
    cutoff = time.time() - RETENTION_DAYS * 86400
    try:
        with _lock:
            con = get_connection()
            if con is None:
                return 0
            cur = con.execute("DELETE FROM api_call_log WHERE ts < ?", (cutoff,))
            con.commit()
            return cur.rowcount
    except Exception:
        logger.exception("Failed to purge old api_call_log rows (non-fatal)")
        return 0
