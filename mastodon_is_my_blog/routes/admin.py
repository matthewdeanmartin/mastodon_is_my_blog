# mastodon_is_my_blog/routes/admin.py
import logging

from fastapi import Depends
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
