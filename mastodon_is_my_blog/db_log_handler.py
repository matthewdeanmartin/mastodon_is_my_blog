"""
stdlib logging.Handler that writes WARNING+ records to the error_log table.

Uses a raw sqlite3 connection (same pattern as api_log.py) so it is safe to
call from synchronous code and from inside asyncio.to_thread without touching
the async SQLAlchemy engine or the event loop.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time

from mastodon_is_my_blog.db_backend import is_sqlite, resolve_backend
from mastodon_is_my_blog.db_path import get_sqlite_file_path

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

RETENTION_DAYS = 30


def get_connection() -> sqlite3.Connection | None:
    """Raw sqlite3 connection to the error_log table, or None off the sqlite
    backend (this telemetry writer is sqlite-only; on postgres/turso it no-ops
    rather than raising)."""
    global _conn
    if not is_sqlite(resolve_backend()):
        return None
    if _conn is None:
        path = get_sqlite_file_path()
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
    return _conn


class DbLogHandler(logging.Handler):
    """Writes WARNING/ERROR/CRITICAL log records into the error_log table."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            exc_text: str | None = None
            if record.exc_info:
                exc_text = logging.Formatter().formatException(record.exc_info)
            with _lock:
                con = get_connection()
                if con is None:
                    return  # non-sqlite backend: error_log is sqlite-only
                con.execute(
                    """
                    INSERT INTO error_log (ts, level, logger_name, message, exc_text)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        time.time(),
                        record.levelname,
                        record.name,
                        record.getMessage(),
                        exc_text,
                    ),
                )
                con.commit()
        except Exception:
            self.handleError(record)


def purge_old_rows() -> int:
    cutoff = time.time() - RETENTION_DAYS * 86400
    try:
        with _lock:
            con = get_connection()
            if con is None:
                return 0
            cur = con.execute("DELETE FROM error_log WHERE ts < ?", (cutoff,))
            con.commit()
            return cur.rowcount
    except Exception:
        return 0
