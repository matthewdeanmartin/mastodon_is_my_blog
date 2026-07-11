"""Backend-agnostic buffer for telemetry writes (api_call_log, error_log).

The writers are called from synchronous code — the stdlib logging handler and
the timed Mastodon client running inside asyncio.to_thread — so they cannot
touch the async SQLAlchemy engine directly. They enqueue rows on a
thread-safe queue; an asyncio flusher (started in main.py's lifespan, or an
explicit flush() at the end of CLI commands) bulk-inserts them through the
normal ORM models. Same behavior on sqlite, postgres, and turso — this
replaces the old raw-sqlite3 writers that silently no-opped off sqlite.

Telemetry is best-effort by design: if the process dies before a flush, the
last interval's rows are lost; if nothing ever flushes, the bounded queue
drops rows rather than growing without limit.
"""

from __future__ import annotations

import asyncio
import logging
import queue
from typing import Any

from mastodon_is_my_blog.store import ApiCallLog, ErrorLog, async_session

logger = logging.getLogger(__name__)

MAX_PENDING_ROWS = 10_000
FLUSH_INTERVAL_SECONDS = 2.0

# (model class, row dict) pairs
PENDING: queue.SimpleQueue = queue.SimpleQueue()

FLUSHER_TASK: asyncio.Task | None = None
FLUSHER_STOP: asyncio.Event | None = None

# Marker for log records emitted by the flusher itself; DbLogHandler skips
# them so a failing flush can't feed the queue it is failing to drain.
INTERNAL_LOG_FLAG = "telemetry_internal"
INTERNAL = {"extra": {INTERNAL_LOG_FLAG: True}}


def enqueue_api_call(
    *,
    method_name: str,
    identity_acct: str | None,
    elapsed_s: float,
    payload_bytes: int,
    ok: bool,
    throttled: bool,
    error_type: str | None,
    ts: float,
) -> None:
    enqueue_row(
        ApiCallLog,
        {
            "ts": ts,
            "method_name": method_name,
            "identity_acct": identity_acct,
            "elapsed_s": elapsed_s,
            "payload_bytes": payload_bytes,
            "ok": 1 if ok else 0,
            "throttled": 1 if throttled else 0,
            "error_type": error_type,
        },
    )


def enqueue_error_log(
    *,
    ts: float,
    level: str,
    logger_name: str,
    message: str,
    exc_text: str | None,
) -> None:
    enqueue_row(
        ErrorLog,
        {
            "ts": ts,
            "level": level,
            "logger_name": logger_name,
            "message": message,
            "exc_text": exc_text,
        },
    )


def enqueue_row(model: type, row: dict[str, Any]) -> None:
    if PENDING.qsize() >= MAX_PENDING_ROWS:
        return  # nothing is flushing; dropping beats unbounded growth
    PENDING.put((model, row))


async def flush() -> int:
    """Drain the queue into the database. Returns rows written (0 on failure —
    telemetry must never take the caller down)."""
    rows: list[tuple[type, dict[str, Any]]] = []
    while True:
        try:
            rows.append(PENDING.get_nowait())
        except queue.Empty:
            break
    if not rows:
        return 0

    try:
        async with async_session() as session:
            session.add_all(model(**row) for model, row in rows)
            await session.commit()
        return len(rows)
    except Exception:
        logger.warning("telemetry flush failed; %d rows dropped", len(rows), exc_info=True, extra=INTERNAL["extra"])
        return 0


async def run_flusher(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=FLUSH_INTERVAL_SECONDS)
        except TimeoutError:
            pass
        await flush()


def start_flusher() -> None:
    global FLUSHER_TASK, FLUSHER_STOP
    if FLUSHER_TASK is not None and not FLUSHER_TASK.done():
        return
    FLUSHER_STOP = asyncio.Event()
    FLUSHER_TASK = asyncio.create_task(run_flusher(FLUSHER_STOP), name="telemetry-flusher")


async def stop_flusher() -> None:
    """Signal the flusher to stop and wait for its final flush."""
    global FLUSHER_TASK, FLUSHER_STOP
    if FLUSHER_STOP is not None:
        FLUSHER_STOP.set()
    if FLUSHER_TASK is not None:
        try:
            await FLUSHER_TASK
        except asyncio.CancelledError:
            pass
    FLUSHER_TASK = None
    FLUSHER_STOP = None
