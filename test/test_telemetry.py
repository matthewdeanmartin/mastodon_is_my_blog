from __future__ import annotations

import logging
import queue

import pytest
from sqlalchemy import select

from mastodon_is_my_blog import telemetry
from mastodon_is_my_blog.db_log_handler import DbLogHandler
from mastodon_is_my_blog.mastodon_apis.api_log import log_api_call
from mastodon_is_my_blog.store import ApiCallLog, ErrorLog


@pytest.fixture(autouse=True)
def fresh_queue(monkeypatch):
    monkeypatch.setattr(telemetry, "PENDING", queue.SimpleQueue())


@pytest.mark.asyncio
async def test_api_call_enqueue_and_flush_lands_rows(patch_async_session, db_session):
    patch_async_session(telemetry)

    log_api_call(
        method_name="timeline_home",
        identity_acct="mistersql@mastodon.social",
        elapsed_s=0.42,
        payload_bytes=1234,
        ok=True,
        throttled=False,
        error_type=None,
    )
    written = await telemetry.flush()

    assert written == 1
    rows = (await db_session.execute(select(ApiCallLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].method_name == "timeline_home"
    assert rows[0].ok == 1
    assert rows[0].throttled == 0


@pytest.mark.asyncio
async def test_db_log_handler_persists_warning_records(patch_async_session, db_session):
    patch_async_session(telemetry)

    log = logging.getLogger("test.telemetry.handler")
    log.setLevel(logging.WARNING)
    handler = DbLogHandler(level=logging.WARNING)
    log.addHandler(handler)
    try:
        log.warning("something looks off: %s", "details")
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            log.exception("it broke")
    finally:
        log.removeHandler(handler)

    written = await telemetry.flush()
    assert written == 2

    rows = (await db_session.execute(select(ErrorLog).order_by(ErrorLog.id))).scalars().all()
    assert [row.level for row in rows] == ["WARNING", "ERROR"]
    assert rows[0].message == "something looks off: details"
    assert rows[0].logger_name == "test.telemetry.handler"
    assert "RuntimeError: boom" in (rows[1].exc_text or "")


def test_db_log_handler_skips_internal_flusher_records():
    log = logging.getLogger("test.telemetry.internal")
    log.setLevel(logging.WARNING)
    handler = DbLogHandler(level=logging.WARNING)
    log.addHandler(handler)
    try:
        log.warning("flush failed", extra={telemetry.INTERNAL_LOG_FLAG: True})
    finally:
        log.removeHandler(handler)

    assert telemetry.PENDING.qsize() == 0


def test_queue_is_bounded(monkeypatch):
    monkeypatch.setattr(telemetry, "MAX_PENDING_ROWS", 5)
    for i in range(10):
        telemetry.enqueue_error_log(ts=float(i), level="WARNING", logger_name="x", message=str(i), exc_text=None)
    assert telemetry.PENDING.qsize() == 5


@pytest.mark.asyncio
async def test_flush_failure_drops_rows_without_raising(monkeypatch):
    class ExplodingSession:
        def __call__(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(telemetry, "async_session", ExplodingSession())
    telemetry.enqueue_error_log(ts=1.0, level="WARNING", logger_name="x", message="hi", exc_text=None)

    assert await telemetry.flush() == 0
    assert telemetry.PENDING.qsize() == 0  # dropped, not stuck


@pytest.mark.asyncio
async def test_purge_old_rows_uses_orm(patch_async_session, db_session):
    import mastodon_is_my_blog.store as store_module

    # purge functions do `from store import async_session` at call time
    patch_async_session(telemetry, store_module)

    db_session.add(ErrorLog(ts=1.0, level="WARNING", logger_name="old", message="ancient"))
    db_session.add(ApiCallLog(ts=1.0, method_name="old_call", elapsed_s=0.1, payload_bytes=0, ok=1, throttled=0))
    await db_session.commit()

    from mastodon_is_my_blog.db_log_handler import purge_old_rows as purge_errors
    from mastodon_is_my_blog.mastodon_apis.api_log import purge_old_rows as purge_calls

    assert await purge_errors() == 1
    assert await purge_calls() == 1
