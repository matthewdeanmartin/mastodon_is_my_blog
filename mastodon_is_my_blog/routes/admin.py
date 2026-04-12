# mastodon_is_my_blog/routes/admin.py
import logging
from typing import Literal

from fastapi import Depends, HTTPException
from fastapi.routing import APIRouter
from sqlalchemy import select

from mastodon_is_my_blog.mastodon_apis.masto_client import (
    client,
    client_from_identity,
)
from mastodon_is_my_blog.queries import get_current_meta_account, sync_all_identities
from mastodon_is_my_blog.store import (
    MastodonIdentity,
    MetaAccount,
    async_session,
    get_last_sync,
)
from mastodon_is_my_blog.utils.perf import (
    card_timings,
    feed_timings,
    preview_cache_counters,
    stage_timings,
    time_async_function,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/sync")
@time_async_function
async def trigger_sync(
    force: bool = True, meta: MetaAccount = Depends(get_current_meta_account)
) -> dict:
    res = await sync_all_identities(meta, force=force)
    return {"results": res}


@router.get("/identities")
async def list_identities(meta: MetaAccount = Depends(get_current_meta_account)):
    async with async_session() as session:
        stmt = select(MastodonIdentity).where(
            MastodonIdentity.meta_account_id == meta.id
        )
        res = (await session.execute(stmt)).scalars().all()
        return [{"id": i.id, "acct": i.acct, "base_url": i.api_base_url} for i in res]


@router.post("/identities")
async def add_identity(
    base_url: str,
    code: str,
    client_id: str,
    client_secret: str,
    meta: MetaAccount = Depends(get_current_meta_account),
):
    """
    Exchanges code for token and saves identity.
    (Simplified OAuth flow - normally requires redirect)
    """
    # Create temp client to exchange code
    m = client(base_url=base_url, client_id=client_id, client_secret=client_secret)
    access_token = m.log_in(code=code, scopes=["read", "write"])
    me = m.account_verify_credentials()

    async with async_session() as session:
        new_id = MastodonIdentity(
            meta_account_id=meta.id,
            api_base_url=base_url,
            client_id=client_id,
            client_secret=client_secret,
            access_token=access_token,
            acct=me["acct"],
            account_id=str(me["id"]),
        )
        session.add(new_id)
        await session.commit()
    return {"status": "created", "acct": me["acct"]}


@router.get("/status")
async def admin_status() -> dict:
    """Get connection status and current user info"""

    # Try to get default identity
    current_user = None
    connected = False

    async with async_session() as session:
        stmt = select(MetaAccount).where(MetaAccount.username == "default")
        meta = (await session.execute(stmt)).scalar_one_or_none()

        if meta:
            stmt = (
                select(MastodonIdentity)
                .where(MastodonIdentity.meta_account_id == meta.id)
                .limit(1)
            )
            identity = (await session.execute(stmt)).scalar_one_or_none()

            if identity and identity.access_token:
                connected = True
                try:
                    m = client_from_identity(identity)
                    me = m.account_verify_credentials()
                    current_user = {
                        "acct": me["acct"],
                        "display_name": me["display_name"],
                        "avatar": me["avatar"],
                        "note": me.get("note", ""),
                    }
                except Exception as e:
                    logger.error(e)
                    logger.error("Failed to verify credentials: %s", e)
                    connected = False

    last_sync = await get_last_sync()

    return {
        "connected": connected,
        "last_sync": last_sync.isoformat() if last_sync else None,
        "current_user": current_user,
    }


@router.get("/perf")
async def get_perf_stats(last_n: int = 50) -> dict:
    """
    Returns recent performance telemetry.

    - stage_timings: last N sync-stage timings (sync_friends, sync_blog_roll,
      sync_notifications, sync_timeline).
    - feed_timings: last N feed-query timings captured by the request middleware.
    - card_timings: last N link-preview card fetch timings.
    - preview_cache: running hit/miss/stale/error counters for the preview cache.
    """
    n = max(1, min(last_n, 200))

    def stage_to_dict(t) -> dict:
        return {
            "stage": t.stage,
            "elapsed_s": round(t.elapsed_s, 3),
            "rows_fetched": t.rows_fetched,
            "rows_written": t.rows_written,
            "rows_skipped": t.rows_skipped,
            "cache_hits": t.cache_hits,
            "extra": t.extra,
            "ts": t.ts,
            "ok": t.ok,
            "error": t.error,
        }

    def feed_to_dict(t) -> dict:
        return {
            "query": t.query,
            "elapsed_s": round(t.elapsed_s, 3),
            "row_count": t.row_count,
            "ts": t.ts,
        }

    def card_to_dict(t) -> dict:
        return {
            "url": t.url,
            "elapsed_s": round(t.elapsed_s, 3),
            "cache_status": t.cache_status,
            "ts": t.ts,
        }

    recent_stages = list(stage_timings)[-n:]
    recent_feeds = list(feed_timings)[-n:]
    recent_cards = list(card_timings)[-n:]

    return {
        "stage_timings": [stage_to_dict(t) for t in reversed(recent_stages)],
        "feed_timings": [feed_to_dict(t) for t in reversed(recent_feeds)],
        "card_timings": [card_to_dict(t) for t in reversed(recent_cards)],
        "preview_cache": preview_cache_counters.as_dict(),
    }


# ---------------------------------------------------------------------------
# 4.5  Catch-up endpoints
# ---------------------------------------------------------------------------


async def _get_identity(meta: MetaAccount, identity_id: int | None) -> MastodonIdentity:
    """Resolve an identity for the given meta account."""
    async with async_session() as session:
        if identity_id is not None:
            stmt = select(MastodonIdentity).where(
                MastodonIdentity.id == identity_id,
                MastodonIdentity.meta_account_id == meta.id,
            )
        else:
            stmt = (
                select(MastodonIdentity)
                .where(MastodonIdentity.meta_account_id == meta.id)
                .limit(1)
            )
        identity = (await session.execute(stmt)).scalar_one_or_none()
        if not identity:
            raise HTTPException(404, "Identity not found")
        return identity


@router.post("/catchup")
async def start_catchup(
    mode: Literal["urgent", "trickle"] = "urgent",
    identity_id: int | None = None,
    max_accounts: int | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """
    Start a catch-up job.

    - mode=urgent  : up to 20 pages per account (~800 posts), fast
    - mode=trickle : unlimited pages per account (full history), slow
    - max_accounts : cap the priority queue length (useful for testing)

    Returns 409 if a job is already running for this identity.
    """
    from mastodon_is_my_blog.catchup_runner import start_job, job_status

    identity = await _get_identity(meta, identity_id)

    try:
        job = await start_job(meta, identity, mode=mode, max_accounts=max_accounts)
    except ValueError as exc:
        raise HTTPException(409, str(exc))

    return {"started": True, **job_status(job)}


@router.get("/catchup/status")
async def catchup_status(
    identity_id: int | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """
    Return the status of the current or most recent catch-up job.
    Returns 404 if no job has been started for this identity.
    """
    from mastodon_is_my_blog.catchup_runner import get_job, job_status

    identity = await _get_identity(meta, identity_id)
    job = get_job(meta.id, identity.id)
    if job is None:
        raise HTTPException(404, "No catch-up job found for this identity")
    return job_status(job)


@router.delete("/catchup")
async def cancel_catchup(
    identity_id: int | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """
    Signal the running catch-up job to stop between accounts.
    Returns 404 if no running job exists.
    """
    from mastodon_is_my_blog.catchup_runner import cancel_job

    identity = await _get_identity(meta, identity_id)
    cancelled = cancel_job(meta.id, identity.id)
    if not cancelled:
        raise HTTPException(404, "No running catch-up job for this identity")
    return {"cancelled": True}


@router.get("/catchup/queue")
async def catchup_queue_preview(
    identity_id: int | None = None,
    max_accounts: int = 10,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """
    Preview the first N accounts in catch-up priority order without starting a job.
    Useful for the Admin UI to show what would run next.
    """
    from mastodon_is_my_blog.catchup import get_catchup_queue

    identity = await _get_identity(meta, identity_id)
    queue = await get_catchup_queue(meta.id, identity.id, max_accounts=max_accounts)
    return {
        "identity_id": identity.id,
        "queue": [
            {
                "acct": a.acct,
                "display_name": a.display_name,
                "is_followed_by": a.is_followed_by,
                "last_status_at": a.last_status_at.isoformat() if a.last_status_at else None,
            }
            for a in queue
        ],
    }
