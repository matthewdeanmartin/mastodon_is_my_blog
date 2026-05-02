# mastodon_is_my_blog/routes/admin.py
import logging
from typing import Literal

from fastapi import Depends, HTTPException, Query as QueryParam, Request
from fastapi.routing import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from mastodon_is_my_blog.account_config import (
    ConfiguredAccount,
    build_unique_account_name,
    list_account_summaries,
    normalize_account_name,
    set_account_credentials,
    upsert_configured_account,
)
from mastodon_is_my_blog.bulk_sync_jobs import (
    cancel_job,
    get_job,
    job_status,
    start_bulk_job,
)
from mastodon_is_my_blog.content_hub_service import (
    create_client_bundle,
    update_client_bundle,
)
from mastodon_is_my_blog.mastodon_apis.masto_client import (
    client,
    client_from_identity,
    identity_has_access_token,
)
from mastodon_is_my_blog.queries import (
    get_current_meta_account,
    recompute_account_post_stats,
    sync_all_following_for_identity,
    sync_all_identities,
    sync_my_favourites_for_identity,
    sync_user_timeline_for_identity,
)
from mastodon_is_my_blog.store import (
    ContentHubGroup,
    ContentHubGroupTerm,
    MastodonIdentity,
    MetaAccount,
    async_session,
    get_last_sync,
    sync_configured_identities,
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
async def trigger_sync(force: bool = True, meta: MetaAccount = Depends(get_current_meta_account)) -> dict:
    res = await sync_all_identities(meta, force=force)
    return {"results": res}


@router.post("/sync-all-following")
async def start_sync_all_following(
    identity_id: int | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """
    One-shot paginated download of the full following + followers lists for
    an identity. Populates cached_accounts so the blogroll and per-person
    views work for every followed account, not just recent posters.
    """
    identity = await _get_identity(meta, identity_id)

    async def runner(on_progress, cancelled):
        return await sync_all_following_for_identity(meta.id, identity, on_progress=on_progress, cancelled=cancelled)

    try:
        job = await start_bulk_job("following", meta.id, identity.id, runner)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    return {"started": True, **job_status(job)}


@router.get("/sync-all-following/status")
async def sync_all_following_status(
    identity_id: int | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    identity = await _get_identity(meta, identity_id)
    job = get_job("following", meta.id, identity.id)
    if job is None:
        raise HTTPException(404, "No following-sync job found for this identity")
    return job_status(job)


@router.delete("/sync-all-following")
async def cancel_sync_all_following(
    identity_id: int | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    identity = await _get_identity(meta, identity_id)
    cancelled = cancel_job("following", meta.id, identity.id)
    if not cancelled:
        raise HTTPException(404, "No running following-sync job for this identity")
    return {"cancelled": True}


@router.post("/sync-all-notifications")
async def start_sync_all_notifications(
    identity_id: int | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """
    One-shot paginated download of the identity's full notification history.
    Required so the Readers blogroll filter surfaces every historical
    reposter, not just the last 80 interactions.
    """
    from mastodon_is_my_blog.notification_sync import (
        sync_all_notifications_for_identity,
    )

    identity = await _get_identity(meta, identity_id)

    async def runner(on_progress, cancelled):
        return await sync_all_notifications_for_identity(meta.id, identity, on_progress=on_progress, cancelled=cancelled)

    try:
        job = await start_bulk_job("notifications", meta.id, identity.id, runner)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    return {"started": True, **job_status(job)}


@router.get("/sync-all-notifications/status")
async def sync_all_notifications_status(
    identity_id: int | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    identity = await _get_identity(meta, identity_id)
    job = get_job("notifications", meta.id, identity.id)
    if job is None:
        raise HTTPException(404, "No notifications-sync job found for this identity")
    return job_status(job)


@router.delete("/sync-all-notifications")
async def cancel_sync_all_notifications(
    identity_id: int | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    identity = await _get_identity(meta, identity_id)
    cancelled = cancel_job("notifications", meta.id, identity.id)
    if not cancelled:
        raise HTTPException(404, "No running notifications-sync job for this identity")
    return {"cancelled": True}


@router.post("/sync-my-favourites")
async def start_sync_my_favourites(
    identity_id: int | None = None,
    full: bool = False,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """Paginated download of the identity's outbound favourites into cached_my_favourites."""
    identity = await _get_identity(meta, identity_id)
    stats = await sync_my_favourites_for_identity(meta.id, identity, full=full)
    return {"synced": True, **stats}


@router.post("/recompute-post-stats")
async def recompute_post_stats(
    identity_id: int | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """
    Recomputes cached_post_count and cached_reply_count on every CachedAccount row
    for the selected identity, using already-cached posts. No API calls made.
    Run this to ensure chatty/broadcaster blogroll filters are up to date.
    """
    identity = await _get_identity(meta, identity_id)
    result = await recompute_account_post_stats(meta.id, identity)
    return {"ok": True, **result}


@router.post("/backfill-content-flags")
async def backfill_content_flags(
    identity_id: int | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """
    Re-analyse already-cached posts to populate has_question and has_book flags
    that were added after initial ingestion. No API calls — reads only from cache.
    """
    from mastodon_is_my_blog.inspect_post import analyze_content_domains
    from mastodon_is_my_blog.store import CachedPost
    from sqlalchemy import update
    import json as _json

    identity = await _get_identity(meta, identity_id)

    async with async_session() as session:
        stmt = select(
            CachedPost.id,
            CachedPost.content,
            CachedPost.media_attachments,
            CachedPost.tags,
            CachedPost.is_reply,
        ).where(
            CachedPost.meta_account_id == meta.id,
            CachedPost.fetched_by_identity_id == identity.id,
        )
        rows = (await session.execute(stmt)).all()

    updated = 0
    batch = []
    for row in rows:
        media = _json.loads(row.media_attachments) if row.media_attachments else []
        tags = _json.loads(row.tags) if row.tags else []
        try:
            flags = analyze_content_domains(row.content or "", media, row.is_reply, tags)
        except Exception:
            continue
        batch.append({"id": row.id, "has_question": flags["has_question"], "has_book": flags["has_book"]})

        if len(batch) >= 500:
            async with async_session() as session:
                for item in batch:
                    await session.execute(update(CachedPost).where(CachedPost.id == item["id"]).values(has_question=item["has_question"], has_book=item["has_book"]))
                await session.commit()
            updated += len(batch)
            batch = []

    if batch:
        async with async_session() as session:
            for item in batch:
                await session.execute(update(CachedPost).where(CachedPost.id == item["id"]).values(has_question=item["has_question"], has_book=item["has_book"]))
            await session.commit()
        updated += len(batch)

    return {"ok": True, "updated": updated}


@router.post("/own-account/catchup")
@time_async_function
async def catchup_own_account(
    identity_id: int | None = None,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """
    Fetch the full status history for the selected identity's own account.

    Unlike the regular sync flow, this walks all available pages and does not
    stop at the newest cached post. It is intended to backfill the archive used
    for static blog generation.
    """
    identity = await _get_identity(meta, identity_id)
    result = await sync_user_timeline_for_identity(
        meta.id,
        identity,
        force=True,
        deep=True,
        stop_at_cached=False,
    )
    if result.get("status") == "error":
        raise HTTPException(502, result.get("msg", "Own-account catch-up failed"))
    return result


@router.get("/identities")
async def list_identities(meta: MetaAccount = Depends(get_current_meta_account)):
    async with async_session() as session:
        stmt = select(MastodonIdentity).where(MastodonIdentity.meta_account_id == meta.id)
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
    existing_names = {summary.name for summary in list_account_summaries()}
    preferred_name = normalize_account_name(me["acct"])
    config_name = build_unique_account_name(preferred_name, existing_names)
    upsert_configured_account(ConfiguredAccount(name=config_name, base_url=base_url))
    set_account_credentials(
        config_name,
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
    )
    await sync_configured_identities()

    async with async_session() as session:
        stmt = select(MastodonIdentity).where(
            MastodonIdentity.meta_account_id == meta.id,
            MastodonIdentity.config_name == config_name,
        )
        new_id = (await session.execute(stmt)).scalar_one()
        new_id.acct = me["acct"]
        new_id.account_id = str(me["id"])
        await session.commit()
    return {"status": "created", "acct": me["acct"]}


@router.get("/status")
async def admin_status() -> dict:
    """Get connection status and current user info"""
    # Try to get default identity
    current_user = None
    connected = False

    async with async_session() as session:
        stmt_meta = select(MetaAccount).where(MetaAccount.username == "default")
        meta = (await session.execute(stmt_meta)).scalar_one_or_none()

        if meta:
            stmt_identity = select(MastodonIdentity).where(MastodonIdentity.meta_account_id == meta.id).limit(1)
            identity = (await session.execute(stmt_identity)).scalar_one_or_none()

            if identity and identity_has_access_token(identity):
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
# Content Hub bundle CRUD
# ---------------------------------------------------------------------------


class TermInput(BaseModel):
    term: str
    term_type: str  # hashtag | search


class BundleCreateRequest(BaseModel):
    name: str
    terms: list[TermInput] = []


class BundleUpdateRequest(BaseModel):
    name: str | None = None
    terms: list[TermInput] | None = None


def group_to_dict(group: ContentHubGroup, terms: list[ContentHubGroupTerm]) -> dict:
    return {
        "id": group.id,
        "name": group.name,
        "slug": group.slug,
        "source_type": group.source_type,
        "is_read_only": group.is_read_only,
        "last_fetched_at": (group.last_fetched_at.isoformat() if group.last_fetched_at else None),
        "created_at": group.created_at.isoformat(),
        "updated_at": group.updated_at.isoformat(),
        "terms": [
            {
                "id": t.id,
                "term": t.term,
                "term_type": t.term_type,
                "normalized_term": t.normalized_term,
            }
            for t in terms
        ],
    }


@router.get("/content-hub/bundles")
async def list_bundles(
    identity_id: int = QueryParam(...),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> list[dict]:
    """List all content hub groups (bundles + server follows) for the current identity."""
    from sqlalchemy.orm import selectinload

    async with async_session() as session:
        stmt = (
            select(ContentHubGroup)
            .options(selectinload(ContentHubGroup.terms))
            .where(
                ContentHubGroup.meta_account_id == meta.id,
                ContentHubGroup.identity_id == identity_id,
            )
            .order_by(ContentHubGroup.source_type, ContentHubGroup.name)
        )
        groups = (await session.execute(stmt)).scalars().all()
        return [group_to_dict(g, g.terms) for g in groups]


@router.post("/content-hub/bundles")
async def create_bundle(
    body: BundleCreateRequest,
    identity_id: int = QueryParam(...),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """Create a new client-side bundle for the current identity."""
    group = await create_client_bundle(
        meta.id,
        identity_id,
        body.name,
        [{"term": t.term, "term_type": t.term_type} for t in body.terms],
    )
    async with async_session() as session:
        stmt = select(ContentHubGroupTerm).where(ContentHubGroupTerm.group_id == group.id)
        terms = (await session.execute(stmt)).scalars().all()
    return group_to_dict(group, list(terms))


@router.put("/content-hub/bundles/{bundle_id}")
async def update_bundle(
    bundle_id: int,
    body: BundleUpdateRequest,
    identity_id: int = QueryParam(...),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """Update name and/or terms of a client-side bundle."""
    try:
        group = await update_client_bundle(
            meta.id,
            identity_id,
            bundle_id,
            body.name,
            ([{"term": t.term, "term_type": t.term_type} for t in body.terms] if body.terms is not None else None),
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

    async with async_session() as session:
        stmt = select(ContentHubGroupTerm).where(ContentHubGroupTerm.group_id == group.id)
        terms = (await session.execute(stmt)).scalars().all()
    return group_to_dict(group, list(terms))


@router.delete("/content-hub/bundles/{bundle_id}")
async def delete_bundle(
    bundle_id: int,
    identity_id: int = QueryParam(...),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    """Delete a client-side bundle."""
    async with async_session() as session:
        group = await session.get(ContentHubGroup, bundle_id)
        if group is None or group.meta_account_id != meta.id or group.identity_id != identity_id:
            raise HTTPException(404, "Bundle not found")
        if group.is_read_only:
            raise HTTPException(403, "Cannot delete a read-only server-follow group")
        await session.delete(group)
        await session.commit()
    return {"deleted": True, "id": bundle_id}


# ---------------------------------------------------------------------------
# NLP topic backfill
# ---------------------------------------------------------------------------

NLP_JOB_KIND = "nlp_backfill"
NLP_META_ID = 0  # not identity-scoped; use a sentinel identity_id


@router.get("/nlp-backfill/status")
async def nlp_backfill_status(
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    from sqlalchemy import text as sa_text

    job = get_job(NLP_JOB_KIND, meta.id, NLP_META_ID)

    async with async_session() as session:
        total_threads = (
            await session.execute(
                sa_text("SELECT COUNT(DISTINCT root_id) FROM cached_posts WHERE meta_account_id = :mid AND root_id IS NOT NULL"),
                {"mid": meta.id},
            )
        ).scalar() or 0

        done_threads = (
            await session.execute(
                sa_text("SELECT COUNT(*) FROM cached_posts WHERE meta_account_id = :mid AND root_id = id AND thread_uncommon_words IS NOT NULL"),
                {"mid": meta.id},
            )
        ).scalar() or 0

    needs_run = done_threads < total_threads

    return {
        "total_threads": total_threads,
        "done_threads": done_threads,
        "needs_run": needs_run,
        "job": job_status(job) if job else None,
    }


@router.post("/nlp-backfill/start")
async def start_nlp_backfill(
    request: Request,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    from sqlalchemy import text as sa_text

    from mastodon_is_my_blog.text_topics import uncommon_lemmas

    nlp = getattr(request.app.state, "nlp", None)
    if nlp is None:
        raise HTTPException(503, "spaCy model not loaded — install en_core_web_sm first")

    existing = get_job(NLP_JOB_KIND, meta.id, NLP_META_ID)
    if existing is not None and not existing.finished:
        raise HTTPException(409, "NLP backfill already running")

    async def runner(on_progress, cancelled):
        # Load all root posts (id == root_id) and their thread content
        async with async_session() as session:
            root_rows = (
                await session.execute(
                    sa_text("SELECT id, meta_account_id FROM cached_posts WHERE meta_account_id = :mid AND root_id = id"),
                    {"mid": meta.id},
                )
            ).all()

        total = len(root_rows)
        logger.info("NLP backfill: %d threads to process", total)
        on_progress(0, total, "loading")

        done = 0
        batch_size = 50
        updates: list[dict] = []

        for root_row in root_rows:
            if cancelled():
                logger.info("NLP backfill cancelled at %d/%d", done, total)
                break

            root_id = root_row.id
            meta_id = root_row.meta_account_id

            # Fetch all posts in this thread
            async with async_session() as session:
                thread_rows = (
                    await session.execute(
                        sa_text("SELECT content FROM cached_posts WHERE meta_account_id = :mid AND root_id = :rid"),
                        {"mid": meta_id, "rid": root_id},
                    )
                ).all()

            combined = " ".join(r.content for r in thread_rows)
            words = uncommon_lemmas(combined, nlp)
            import json as _json

            updates.append({"root_id": root_id, "meta_id": meta_id, "words": _json.dumps(words)})
            done += 1

            if len(updates) >= batch_size:
                async with async_session() as session:
                    await session.execute(
                        sa_text("UPDATE cached_posts SET thread_uncommon_words = :words WHERE id = :root_id AND meta_account_id = :meta_id AND root_id = id"),
                        updates,
                    )
                    await session.commit()
                logger.info("NLP backfill: %d/%d committed", done, total)
                updates = []
                on_progress(done, total, "processing")

        if updates:
            async with async_session() as session:
                await session.execute(
                    sa_text("UPDATE cached_posts SET thread_uncommon_words = :words WHERE id = :root_id AND meta_account_id = :meta_id AND root_id = id"),
                    updates,
                )
                await session.commit()
            logger.info("NLP backfill: %d/%d final batch committed", done, total)

        on_progress(done, total, "done")
        return {"processed": done, "total": total}

    job = await start_bulk_job(NLP_JOB_KIND, meta.id, NLP_META_ID, runner)
    return {"started": True, **job_status(job)}


@router.delete("/nlp-backfill")
async def cancel_nlp_backfill(
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    cancelled = cancel_job(NLP_JOB_KIND, meta.id, NLP_META_ID)
    if not cancelled:
        raise HTTPException(404, "No running NLP backfill job")
    return {"cancelled": True}


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
            stmt = select(MastodonIdentity).where(MastodonIdentity.meta_account_id == meta.id).limit(1)
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
    from mastodon_is_my_blog.catchup_runner import job_status, start_job  # pylint: disable=reimported,redefined-outer-name

    identity = await _get_identity(meta, identity_id)

    try:
        job = await start_job(meta, identity, mode=mode, max_accounts=max_accounts)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

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
    from mastodon_is_my_blog.catchup_runner import get_job, job_status  # pylint: disable=reimported,redefined-outer-name

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
    from mastodon_is_my_blog.catchup_runner import cancel_job  # pylint: disable=reimported,redefined-outer-name

    identity = await _get_identity(meta, identity_id)
    cancelled = cancel_job(meta.id, identity.id)
    if not cancelled:
        raise HTTPException(404, "No running catch-up job for this identity")
    return {"cancelled": True}


@router.get("/error-log")
async def get_error_log(limit: int = 200) -> list[dict]:
    """Return recent WARNING/ERROR/CRITICAL log records from the error_log table."""
    import sqlite3
    from datetime import datetime

    from mastodon_is_my_blog.db_path import get_sqlite_file_path

    path = get_sqlite_file_path()
    con = sqlite3.connect(path)
    try:
        rows = con.execute(
            "SELECT id, ts, level, logger_name, message, exc_text FROM error_log ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        con.close()

    return [
        {
            "id": r[0],
            "ts": r[1],
            "iso": datetime.utcfromtimestamp(r[1]).isoformat() + "Z",
            "level": r[2],
            "logger": r[3],
            "message": r[4],
            "exc_text": r[5],
        }
        for r in rows
    ]


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
                "last_status_at": (a.last_status_at.isoformat() if a.last_status_at else None),
            }
            for a in queue
        ],
    }
