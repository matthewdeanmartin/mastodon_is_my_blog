"""stdlib logging.Handler that persists WARNING+ records to the error_log
table via the telemetry buffer (see telemetry.py), so it works identically on
sqlite and postgres and is safe to call from any thread — the actual database
write happens on the asyncio flusher, never in the logging call.
"""

from __future__ import annotations

import logging
import time
from typing import cast

from mastodon_is_my_blog import telemetry
from sqlalchemy.engine import CursorResult

RETENTION_DAYS = 30


class DbLogHandler(logging.Handler):
    """Buffers WARNING/ERROR/CRITICAL log records for the error_log table."""

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, telemetry.INTERNAL_LOG_FLAG, False):
            return  # the flusher reporting its own failure must not re-enqueue
        try:
            exc_text: str | None = None
            if record.exc_info:
                exc_text = logging.Formatter().formatException(record.exc_info)
            telemetry.enqueue_error_log(
                ts=time.time(),
                level=record.levelname,
                logger_name=record.name,
                message=record.getMessage(),
                exc_text=exc_text,
            )
        except Exception:
            self.handleError(record)


async def purge_old_rows() -> int:
    from sqlalchemy import delete

    from mastodon_is_my_blog.store import ErrorLog, async_session

    cutoff = time.time() - RETENTION_DAYS * 86400
    try:
        async with async_session() as session:
            result = await session.execute(delete(ErrorLog).where(ErrorLog.ts < cutoff))
            await session.commit()
            return cast("CursorResult", result).rowcount or 0
    except Exception:
        return 0
