# Sprint 05 — Backend-agnostic error log + API observability telemetry

Status: done

## Problem

The Postgres migration left telemetry sqlite-only:
- `db_log_handler.py` and `mastodon_apis/api_log.py` write via raw `sqlite3`
  and silently no-op on postgres → error_log/api_call_log stay empty →
  observability page truthfully shows zeros.
- `GET /api/admin/error-log` still reads via `sqlite3.connect(get_sqlite_file_path())`,
  which raises on postgres → 500 → "Failed to load error log" in the UI.
Both tables exist on all backends (SQLAlchemy models `ApiCallLog`, `ErrorLog`).
duck.py observability queries already attach postgres fine — only writes died.

## Design

No sync postgres driver in deps (asyncpg only), and writers run in sync
contexts (logging handler, timed client inside asyncio.to_thread) — so:
**thread-safe in-memory buffer + asyncio flusher** writing through the normal
SQLAlchemy models. One code path for sqlite/postgres/turso; raw sqlite3
connections deleted.

- New `telemetry.py`: bounded `queue.SimpleQueue` (drop when > 10k),
  `enqueue_api_call(...)` / `enqueue_error_log(...)` (sync, cheap),
  `async flush()` bulk-insert via `async_session`, `start_flusher()` /
  `stop_flusher()` for the app lifespan (2 s interval, final flush on stop).
  Flusher logs its own failures with `extra={"telemetry_internal": True}`;
  DbLogHandler skips those records to avoid a feedback loop.
- `db_log_handler.py`: emit → enqueue; purge → async SQLAlchemy DELETE.
- `api_log.py`: log_api_call → enqueue; purge → async SQLAlchemy DELETE.
- `queries.py`: purges awaited directly (no more to_thread).
- `routes/admin.py` get_error_log → `select(ErrorLog)` (fixes the 500).
- `main.py` lifespan: start flusher on startup, stop+flush on shutdown.
- `admin_cli.py`: CLI commands flush telemetry before exiting their loop.

## Tests

`test/test_telemetry.py` with the existing `patch_async_session` fixture:
enqueue+flush lands ApiCallLog/ErrorLog rows; DbLogHandler.emit → flush
persists level/message/exc_text; internal-flag records skipped; queue cap
drops instead of growing; error-log endpoint reads via ORM (route test).

## Result

- Implemented exactly as designed; raw sqlite3 telemetry connections deleted.
- error-log endpoint also flushes the buffer before reading, so fresh
  warnings appear immediately instead of after the next flusher tick.
- Tests: test/test_telemetry.py (6 tests: flush lands ApiCallLog/ErrorLog
  rows, handler round-trip incl. exc_text, internal-flag skip, bounded queue,
  flush-failure drop, ORM purges). Full suite 446 passed.
- E2E verified with a live app lifespan on scratch sqlite: warning →
  /api/admin/error-log 200 with the row; log_api_call + the app's own
  startup verify_credentials calls → /api/observability/by-method rows.
- NOTE: the user's running server needs a restart to pick this up. Telemetry
  from the postgres era before this fix was never written (writers no-oped);
  sqlite-era history still lives in the old sqlite file, portable with
  `mimb db port` if ever wanted.
