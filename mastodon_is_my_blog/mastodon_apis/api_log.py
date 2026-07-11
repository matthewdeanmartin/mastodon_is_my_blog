"""Thread-safe writer for api_call_log via the telemetry buffer (telemetry.py).

Called synchronously by the timed Mastodon client (often inside
asyncio.to_thread); the enqueue is a cheap in-memory put and the database
write happens on the asyncio flusher — identical on sqlite and postgres.
"""

from __future__ import annotations

import logging
import time
from typing import cast

from mastodon_is_my_blog import telemetry

logger = logging.getLogger(__name__)

RETENTION_DAYS = 90


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
        telemetry.enqueue_api_call(
            ts=time.time(),
            method_name=method_name,
            identity_acct=identity_acct,
            elapsed_s=elapsed_s,
            payload_bytes=payload_bytes,
            ok=ok,
            throttled=throttled,
            error_type=error_type,
        )
    except Exception:
        logger.exception("Failed to enqueue api_call_log row (non-fatal)")


async def purge_old_rows() -> int:
    from sqlalchemy import delete
    from sqlalchemy.engine import CursorResult

    from mastodon_is_my_blog.store import ApiCallLog, async_session

    cutoff = time.time() - RETENTION_DAYS * 86400
    try:
        async with async_session() as session:
            result = await session.execute(delete(ApiCallLog).where(ApiCallLog.ts < cutoff))
            await session.commit()
            return cast(CursorResult, result).rowcount or 0
    except Exception:
        logger.exception("Failed to purge old api_call_log rows (non-fatal)")
        return 0
