"""
4.4  Catch-up coordinator.

Module-level CATCHUP dict holds one CatchupJob per (meta_id, identity_id).
Jobs are asyncio Tasks that run on the server's event loop — no Celery needed.

Modes:
  urgent  — serial walk, max_pages=20 per account (~800 posts cap), 200 ms
             inter-account delay.  Good for "I was away a week".
  trickle — serial walk, max_pages=None (all the way back), 5 s inter-account
             delay.  Good for "pull everything the instance has ever served".
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


from mastodon_is_my_blog.catchup import (
    RateBudget,
    deep_fetch_user_timeline,
    get_stop_at_id,
)
from mastodon_is_my_blog.datetime_helpers import utc_now
from mastodon_is_my_blog.mastodon_apis.masto_client import client_from_identity
from mastodon_is_my_blog.queries import bulk_upsert_accounts, bulk_upsert_posts
from mastodon_is_my_blog.store import (
    CachedAccount,
    MastodonIdentity,
    MetaAccount,
    async_session,
)

logger = logging.getLogger(__name__)

Mode = Literal["urgent", "trickle"]


@dataclass
class CatchupJob:
    meta_id: int
    identity_id: int
    mode: Mode
    total: int
    done: int = 0
    current_acct: str | None = None
    errors: int = 0
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    rate_limited: bool = False
    # set by start_job after task is created
    task: asyncio.Task | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


# Keyed on (meta_id, identity_id)
CATCHUP: dict[tuple[int, int], CatchupJob] = {}


async def start_job(
    meta: MetaAccount,
    identity: MastodonIdentity,
    mode: Mode,
    max_accounts: int | None = None,
) -> CatchupJob:
    """
    Build the priority queue and launch the background task.
    Raises ValueError if a job is already running for this (meta, identity) pair.
    """
    from mastodon_is_my_blog.catchup import get_catchup_queue

    key = (meta.id, identity.id)
    existing = CATCHUP.get(key)
    if existing and existing.task and not existing.task.done():
        raise ValueError(f"Job already running for identity {identity.id}")

    queue = await get_catchup_queue(meta.id, identity.id, max_accounts=max_accounts)

    job = CatchupJob(
        meta_id=meta.id,
        identity_id=identity.id,
        mode=mode,
        total=len(queue),
    )
    CATCHUP[key] = job

    runner = run_urgent if mode == "urgent" else run_trickle
    job.task = asyncio.create_task(runner(job, queue, identity))
    return job


async def run_urgent(
    job: CatchupJob,
    queue: list[CachedAccount],
    identity: MastodonIdentity,
) -> None:
    """
    Urgent mode: 20 pages max per account, 200 ms between accounts.
    Catches up ~800 posts per followed account quickly.
    """
    await _run_loop(
        job,
        queue,
        identity,
        max_pages=20,
        inter_account_delay=0.2,
    )


async def run_trickle(
    job: CatchupJob,
    queue: list[CachedAccount],
    identity: MastodonIdentity,
) -> None:
    """
    Trickle mode: no page cap (walks all the way back), 5 s between accounts.
    Eventually pulls everything the instance will serve.
    """
    await _run_loop(
        job,
        queue,
        identity,
        max_pages=None,
        inter_account_delay=5.0,
    )


async def _run_loop(
    job: CatchupJob,
    queue: list[CachedAccount],
    identity: MastodonIdentity,
    max_pages: int | None,
    inter_account_delay: float,
) -> None:
    rate_budget = RateBudget()
    m = client_from_identity(identity)
    inter_account_delay_current = inter_account_delay

    for account in queue:
        if job.cancel_event.is_set():
            logger.info("catchup job cancelled at account %s", account.acct)
            break

        job.current_acct = account.acct
        logger.info(
            "catchup [%s] mode=%s account=%s (%d/%d)",
            identity.acct,
            job.mode,
            account.acct,
            job.done + 1,
            job.total,
        )

        try:
            target_id = await asyncio.to_thread(_resolve_account_id, m, account.acct)
            if target_id is None:
                logger.warning("catchup: could not resolve %s, skipping", account.acct)
                job.done += 1
                continue

            stop_at_id = await get_stop_at_id(job.meta_id, identity.id, account.acct)

            consecutive_429s = 0
            async for page in deep_fetch_user_timeline(
                m,
                target_id,
                stop_at_id=stop_at_id,
                max_pages=max_pages,
                rate_budget=rate_budget,
                inter_page_delay=0.5,
            ):
                if job.cancel_event.is_set():
                    break

                # Check whether we hit rate limiting on this page
                # (deep_fetch already slept; we just track it for the UI)
                job.rate_limited = False  # reset; deep_fetch handled the backoff

                async with async_session() as session:
                    await bulk_upsert_accounts(
                        session,
                        job.meta_id,
                        identity.id,
                        [
                            {
                                "account_data": {
                                    "id": account.id,
                                    "acct": account.acct,
                                    "display_name": account.display_name,
                                    "avatar": account.avatar,
                                    "url": account.url,
                                    "note": account.note,
                                    "bot": account.bot,
                                    "locked": account.locked,
                                    "header": account.header,
                                    "fields": [],
                                    "followers_count": account.followers_count,
                                    "following_count": account.following_count,
                                    "statuses_count": account.statuses_count,
                                    "last_status_at": account.last_status_at,
                                }
                            }
                        ],
                    )
                    await bulk_upsert_posts(session, job.meta_id, identity.id, page)
                    await session.commit()

            consecutive_429s = 0
            inter_account_delay_current = inter_account_delay  # reset backoff

        except Exception as exc:
            logger.error("catchup error for %s: %s", account.acct, exc)
            job.errors += 1
            # If it looks like a rate-limit exception, flag it and back off
            if getattr(exc, "retry_after", None) is not None:
                job.rate_limited = True
                inter_account_delay_current = min(
                    inter_account_delay_current * 2, 120.0
                )

        job.done += 1

        if job.cancel_event.is_set():
            break

        await asyncio.sleep(inter_account_delay_current)

    job.current_acct = None
    job.finished_at = utc_now()
    logger.info(
        "catchup [%s] mode=%s finished: %d done, %d errors",
        identity.acct,
        job.mode,
        job.done,
        job.errors,
    )


def _resolve_account_id(m, acct: str) -> str | None:
    """Synchronous helper — called via asyncio.to_thread."""
    try:
        results = m.account_search(acct, limit=1)
        if results:
            return str(results[0]["id"])
        return None
    except Exception as exc:
        logger.error("account_search failed for %s: %s", acct, exc)
        return None


def get_job(meta_id: int, identity_id: int) -> CatchupJob | None:
    return CATCHUP.get((meta_id, identity_id))


def cancel_job(meta_id: int, identity_id: int) -> bool:
    """Signal the job to stop. Returns True if a running job was found."""
    job = CATCHUP.get((meta_id, identity_id))
    if job and job.task and not job.task.done():
        job.cancel_event.set()
        return True
    return False


def job_status(job: CatchupJob) -> dict:
    running = job.task is not None and not job.task.done()
    return {
        "running": running,
        "mode": job.mode,
        "done": job.done,
        "total": job.total,
        "current_acct": job.current_acct,
        "errors": job.errors,
        "started_at": job.started_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "rate_limited": job.rate_limited,
    }
