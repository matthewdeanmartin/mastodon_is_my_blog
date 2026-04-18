from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from mastodon_is_my_blog.catchup import RateBudget, deep_fetch_user_timeline
from mastodon_is_my_blog.datetime_helpers import utc_now
from mastodon_is_my_blog.mastodon_apis.masto_client import client_from_identity
from mastodon_is_my_blog.queries import (
    bulk_upsert_accounts,
    bulk_upsert_posts,
    sync_user_timeline_for_identity,
)
from mastodon_is_my_blog.store import MastodonIdentity, MetaAccount, async_session

logger = logging.getLogger(__name__)

Mode = Literal["recent", "deep"]


@dataclass
class AccountCatchupJob:
    meta_id: int
    identity_id: int
    acct: str
    mode: Mode
    stage: str = "queued"
    pages_fetched: int = 0
    posts_fetched: int = 0
    new_posts: int = 0
    updated_posts: int = 0
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    error: str | None = None
    task: asyncio.Task | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


ACCOUNT_CATCHUP: dict[tuple[int, int, str], AccountCatchupJob] = {}


def _job_key(meta_id: int, identity_id: int, acct: str) -> tuple[int, int, str]:
    return (meta_id, identity_id, acct.casefold())


async def start_job(
    meta: MetaAccount,
    identity: MastodonIdentity,
    acct: str,
    mode: Mode,
) -> AccountCatchupJob:
    key = _job_key(meta.id, identity.id, acct)
    existing = ACCOUNT_CATCHUP.get(key)
    if existing and existing.task and not existing.task.done():
        raise ValueError(f"Job already running for account {acct}")

    job = AccountCatchupJob(
        meta_id=meta.id,
        identity_id=identity.id,
        acct=acct,
        mode=mode,
    )
    ACCOUNT_CATCHUP[key] = job
    job.task = asyncio.create_task(_run_job(job, identity))
    return job


async def _run_job(job: AccountCatchupJob, identity: MastodonIdentity) -> None:
    try:
        if job.mode == "recent":
            await _run_recent(job, identity)
        else:
            await _run_deep(job, identity)
        if job.cancel_event.is_set():
            job.stage = "cancelled"
        elif job.error is None:
            job.stage = "finished"
    except Exception as exc:
        job.error = str(exc)
        job.stage = "error"
        logger.error("account catch-up failed for %s: %s", job.acct, exc)
    finally:
        job.finished_at = utc_now()


async def _run_recent(job: AccountCatchupJob, identity: MastodonIdentity) -> None:
    job.stage = "fetching latest page"
    result = await sync_user_timeline_for_identity(
        meta_id=job.meta_id,
        identity=identity,
        acct=job.acct,
        force=True,
    )
    if result.get("status") == "error":
        raise RuntimeError(result.get("msg", "Recent catch-up failed"))
    if result.get("status") == "not_found":
        raise RuntimeError(f"Account {job.acct} not found")

    job.pages_fetched = 1
    job.posts_fetched = int(result.get("count", 0) or 0)


async def _run_deep(job: AccountCatchupJob, identity: MastodonIdentity) -> None:
    client = client_from_identity(identity)
    job.stage = "resolving account"
    results = await asyncio.to_thread(client.account_search, job.acct, limit=1)
    if not results:
        raise RuntimeError(f"Account {job.acct} not found")

    target_account = results[0]
    target_id = str(target_account["id"])
    rate_budget = RateBudget()

    job.stage = "walking history"
    async for page in deep_fetch_user_timeline(
        client,
        target_id,
        stop_at_id=None,
        max_pages=None,
        rate_budget=rate_budget,
        inter_page_delay=0.5,
    ):
        if job.cancel_event.is_set():
            break

        async with async_session() as session:
            await bulk_upsert_accounts(
                session,
                job.meta_id,
                identity.id,
                [{"account_data": target_account}],
            )
            new_count, updated_count = await bulk_upsert_posts(
                session, job.meta_id, identity.id, page
            )
            await session.commit()

        job.pages_fetched += 1
        job.posts_fetched += len(page)
        job.new_posts += new_count
        job.updated_posts += updated_count
        job.stage = f"fetched page {job.pages_fetched}"


def get_job(meta_id: int, identity_id: int, acct: str) -> AccountCatchupJob | None:
    return ACCOUNT_CATCHUP.get(_job_key(meta_id, identity_id, acct))


def cancel_job(meta_id: int, identity_id: int, acct: str) -> bool:
    job = get_job(meta_id, identity_id, acct)
    if job and job.task and not job.task.done():
        job.cancel_event.set()
        return True
    return False


def job_status(job: AccountCatchupJob) -> dict:
    running = job.task is not None and not job.task.done()
    return {
        "running": running,
        "finished": job.finished_at is not None and not running,
        "acct": job.acct,
        "mode": job.mode,
        "stage": job.stage,
        "pages_fetched": job.pages_fetched,
        "posts_fetched": job.posts_fetched,
        "new_posts": job.new_posts,
        "updated_posts": job.updated_posts,
        "started_at": job.started_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error": job.error,
        "cancel_requested": job.cancel_event.is_set(),
    }
