# mastodon_is_my_blog/queries.py
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import dotenv
from fastapi import HTTPException, Request
from sqlalchemy import Integer, and_, func, outerjoin, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from mastodon_is_my_blog.inspect_post import analyze_content_domains
from mastodon_is_my_blog.mastodon_apis.masto_client import (
    client_from_identity,
)
from mastodon_is_my_blog.store import SeenPost  # ADDED
from mastodon_is_my_blog.utils.perf import sync_stage
from mastodon_is_my_blog.store import (
    CachedAccount,
    CachedPost,
    MastodonIdentity,
    MetaAccount,
    async_session,
    get_last_sync,
    get_token,
    update_last_sync,
)

logger = logging.getLogger(__name__)

dotenv.load_dotenv()


async def get_current_meta_account(request: Request) -> MetaAccount:
    """
    Identifies the Meta Account.
    In a real app, this would verify a JWT or Session Cookie.
    Here, we default to the 'default' user or read a header X-Meta-Account-ID.
    """
    async with async_session() as session:
        # Simple header check for multi-user test capability
        header_id = request.headers.get("X-Meta-Account-ID")
        if header_id:
            stmt = select(MetaAccount).where(MetaAccount.id == int(header_id))
            meta = (await session.execute(stmt)).scalar_one_or_none()
            if meta:
                return meta

        # Fallback to default
        stmt = select(MetaAccount).where(MetaAccount.username == "default")
        return (await session.execute(stmt)).scalar_one()


def to_naive_utc(dt: datetime | None) -> datetime | None:
    """
    Safely converts any datetime (Aware or Naive) to Naive UTC.
    This ensures we can always compare dates with SQLite data without crashing.
    """
    if dt is None:
        return None
    # If it has timezone info, convert to UTC and strip it
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    # If it's already naive, assume it's what we want
    return dt


# --- Sync Engines ---


def build_account_payload(account_data: dict, **overrides: Any) -> dict:
    """Build a row payload for CachedAccount from a Mastodon API account dict."""
    payload = {
        "acct": account_data["acct"],
        "display_name": account_data["display_name"],
        "avatar": account_data["avatar"],
        "url": account_data["url"],
        "note": account_data.get("note", ""),
        "bot": account_data.get("bot", False),
        "locked": account_data.get("locked", False),
        "header": account_data.get("header", ""),
        "created_at": to_naive_utc(account_data.get("created_at")),
        "fields": json.dumps(account_data.get("fields", [])),
        "followers_count": account_data.get("followers_count", 0),
        "following_count": account_data.get("following_count", 0),
        "statuses_count": account_data.get("statuses_count", 0),
    }
    payload.update(overrides)
    return payload


async def bulk_upsert_accounts(
    session: AsyncSession,
    meta_id: int,
    identity_id: int,
    rows: list[dict],
) -> None:
    """
    Bulk upsert CachedAccount rows.

    Each row in `rows` must be a dict with:
      - "account_data": the raw Mastodon API account dict
      - optional "overrides": dict of field overrides (e.g. is_following=True)
      - optional "last_status_at": datetime from an observed status
        (will be max-merged against the existing row)

    Uses sqlite ON CONFLICT DO UPDATE to perform inserts and updates in a
    single round-trip per identity.  Does NOT commit.
    """
    if not rows:
        return

    # Resolve duplicates within the incoming batch: keep the last payload per id,
    # but max-merge any last_status_at values. This avoids the sqlite error
    # "ON CONFLICT DO UPDATE command cannot affect row a second time".
    merged: dict[str, dict] = {}
    merged_last_status: dict[str, datetime | None] = {}
    for row in rows:
        account_data = row["account_data"]
        overrides = row.get("overrides") or {}
        last_status_at = to_naive_utc(row.get("last_status_at"))

        acc_id = str(account_data["id"])
        merged[acc_id] = build_account_payload(account_data, **overrides)

        prev_last = merged_last_status.get(acc_id)
        if last_status_at and (prev_last is None or last_status_at > prev_last):
            merged_last_status[acc_id] = last_status_at
        elif acc_id not in merged_last_status:
            merged_last_status[acc_id] = prev_last

    if not merged:
        return

    # For last_status_at max-merge against existing DB rows, pre-fetch existing values
    # for any ids that carry a last_status_at in this batch.
    ids_with_last = [aid for aid, ts in merged_last_status.items() if ts is not None]
    existing_last: dict[str, datetime | None] = {}
    if ids_with_last:
        stmt = select(CachedAccount.id, CachedAccount.last_status_at).where(
            and_(
                CachedAccount.meta_account_id == meta_id,
                CachedAccount.mastodon_identity_id == identity_id,
                CachedAccount.id.in_(ids_with_last),
            )
        )
        for row_id, prev in (await session.execute(stmt)).all():
            existing_last[row_id] = prev

    # Build final value list with last_status_at max-merged
    values = []
    for acc_id, payload in merged.items():
        row_values = {
            "id": acc_id,
            "meta_account_id": meta_id,
            "mastodon_identity_id": identity_id,
            **payload,
        }
        batch_last = merged_last_status.get(acc_id)
        if batch_last is not None:
            prev_last = existing_last.get(acc_id)
            row_values["last_status_at"] = (
                batch_last if (prev_last is None or batch_last > prev_last) else prev_last
            )
        values.append(row_values)

    # Build the ON CONFLICT DO UPDATE statement.  The update set must exclude the
    # primary key columns; everything else is taken from excluded.*.
    stmt = sqlite_insert(CachedAccount).values(values)
    non_pk_cols = [
        c.name
        for c in CachedAccount.__table__.columns
        if c.name not in ("id", "meta_account_id", "mastodon_identity_id")
    ]
    # Only update columns that were actually present in the incoming payload
    # (e.g. last_status_at may only appear for some callers).
    present_cols = set()
    for v in values:
        present_cols.update(v.keys())
    update_cols = {c: stmt.excluded[c] for c in non_pk_cols if c in present_cols}

    stmt = stmt.on_conflict_do_update(
        index_elements=["id", "meta_account_id", "mastodon_identity_id"],
        set_=update_cols,
    )
    await session.execute(stmt)


def build_post_payload(
    meta_id: int,
    identity_id: int,
    status: dict,
) -> dict:
    """Build a row payload dict for CachedPost from a Mastodon API status dict."""
    is_reblog = status["reblog"] is not None
    actual = status["reblog"] if is_reblog else status

    in_reply_to_id = actual.get("in_reply_to_id")
    in_reply_to_account = actual.get("in_reply_to_account_id")
    is_reply_to_other = in_reply_to_id is not None and str(
        in_reply_to_account
    ) != str(actual["account"]["id"])

    flags = analyze_content_domains(
        actual["content"], actual["media_attachments"], is_reply_to_other
    )
    media_json = (
        json.dumps(actual["media_attachments"])
        if actual["media_attachments"]
        else None
    )
    tags_json = json.dumps([t_tag["name"] for t_tag in status.get("tags", [])])

    return {
        "id": str(status["id"]),
        "meta_account_id": meta_id,
        "fetched_by_identity_id": identity_id,
        "content": actual["content"],
        "created_at": to_naive_utc(status["created_at"]),
        "visibility": status["visibility"],
        "author_acct": actual["account"]["acct"],
        "author_id": str(actual["account"]["id"]),
        "is_reblog": is_reblog,
        "is_reply": is_reply_to_other,
        "in_reply_to_id": str(in_reply_to_id) if in_reply_to_id else None,
        "in_reply_to_account_id": (
            str(in_reply_to_account) if in_reply_to_account else None
        ),
        "has_media": flags["has_media"],
        "has_video": flags["has_video"],
        "has_news": flags["has_news"],
        "has_tech": flags["has_tech"],
        "has_link": flags["has_link"],
        "has_question": flags["has_question"],
        "tags": tags_json,
        "replies_count": status["replies_count"],
        "reblogs_count": status["reblogs_count"],
        "favourites_count": status["favourites_count"],
        "media_attachments": media_json,
    }


async def bulk_upsert_posts(
    session: AsyncSession,
    meta_id: int,
    identity_id: int,
    statuses: list[dict],
    *,
    discovery_source: str = "timeline",
    content_hub_only: bool = False,
) -> tuple[int, int]:
    """
    Bulk upsert CachedPost rows from raw Mastodon API status dicts.

    discovery_source and content_hub_only are applied to all rows in this batch.
    These fields are never overwritten on conflict — the first write wins.

    Returns (new_count, updated_count).  Does NOT commit.
    """
    if not statuses:
        return (0, 0)

    # Deduplicate within the batch — keep the last payload per id
    payloads: dict[str, dict] = {}
    for status in statuses:
        payload = build_post_payload(meta_id, identity_id, status)
        payload["discovery_source"] = discovery_source
        payload["content_hub_only"] = content_hub_only
        payloads[payload["id"]] = payload

    if not payloads:
        return (0, 0)

    # Pre-fetch existing ids to produce accurate (new, updated) counts
    ids = list(payloads.keys())
    existing_ids = set(
        (
            await session.execute(
                select(CachedPost.id).where(
                    and_(
                        CachedPost.meta_account_id == meta_id,
                        CachedPost.fetched_by_identity_id == identity_id,
                        CachedPost.id.in_(ids),
                    )
                )
            )
        ).scalars()
    )

    stmt = sqlite_insert(CachedPost).values(list(payloads.values()))
    # Exclude discovery metadata from conflict updates so that a timeline sync
    # never overwrites content_hub_only / discovery_source set by Content Hub.
    non_pk_cols = [
        c.name
        for c in CachedPost.__table__.columns
        if c.name not in (
            "id", "meta_account_id", "fetched_by_identity_id",
            "discovery_source", "content_hub_only",
        )
    ]
    update_cols = {c: stmt.excluded[c] for c in non_pk_cols}
    stmt = stmt.on_conflict_do_update(
        index_elements=["id", "meta_account_id", "fetched_by_identity_id"],
        set_=update_cols,
    )
    await session.execute(stmt)

    updated_count = len(existing_ids)
    new_count = len(payloads) - updated_count
    return (new_count, updated_count)


async def _upsert_account(
    session: AsyncSession,
    meta_id: int,
    identity_id: int,
    account_data: dict,
    **overrides,
) -> CachedAccount:
    """
    Single-row wrapper that delegates to bulk_upsert_accounts and returns the
    resulting CachedAccount instance (re-fetched).  Kept for legacy callers
    that need the ORM object back (e.g. to mutate last_status_at).
    """
    await bulk_upsert_accounts(
        session,
        meta_id,
        identity_id,
        [{"account_data": account_data, "overrides": overrides}],
    )

    stmt = select(CachedAccount).where(
        and_(
            CachedAccount.id == str(account_data["id"]),
            CachedAccount.meta_account_id == meta_id,
            CachedAccount.mastodon_identity_id == identity_id,
        )
    )
    return (await session.execute(stmt)).scalar_one()


async def sync_all_identities(meta: MetaAccount, force: bool = False) -> list[dict]:
    """Iterates through all identities for the meta account and syncs them."""
    async with async_session() as session:
        result = await session.execute(
            select(MastodonIdentity).where(MastodonIdentity.meta_account_id == meta.id)
        )
        identities = result.scalars().all()

    results = []
    for identity in identities:
        # Sync Friends (following/followers)
        await sync_friends_for_identity(meta.id, identity)

        # Sync Blog Roll (home timeline activity)
        await sync_blog_roll_for_identity(meta.id, identity)

        # Sync Notifications (interactions - critical for top friends)
        from mastodon_is_my_blog.notification_sync import (
            sync_notifications_for_identity,
        )

        notif_stats = await sync_notifications_for_identity(meta.id, identity)

        # Sync Timeline (own posts)
        timeline_res = await sync_user_timeline_for_identity(
            meta.id, identity, force=force
        )

        results.append(
            {
                identity.acct: {
                    "timeline": timeline_res,
                    "notifications": notif_stats,
                }
            }
        )

    return results


async def sync_friends_for_identity(meta_id: int, identity: MastodonIdentity) -> None:
    """Syncs following/followers for a specific identity."""
    async with sync_stage(f"sync_friends:{identity.acct}") as t:
        m = client_from_identity(identity)
        try:
            me = m.account_verify_credentials()
            following = m.account_following(me["id"], limit=80)
            followers = m.account_followers(me["id"], limit=80)
            t.rows_fetched = len(following) + len(followers)

            rows = [
                {"account_data": acc, "overrides": {"is_following": True}}
                for acc in following
            ] + [
                {"account_data": acc, "overrides": {"is_followed_by": True}}
                for acc in followers
            ]

            async with async_session() as session:
                await bulk_upsert_accounts(session, meta_id, identity.id, rows)
                await session.commit()
                t.rows_written = len(rows)
        except Exception as e:
            logger.error(e)
            logger.error("Failed to sync friends for %s: %s", identity.acct, e)
            raise


async def sync_blog_roll_for_identity(meta_id: int, identity: MastodonIdentity) -> None:
    """Syncs home timeline activity for blog roll."""
    async with sync_stage(f"sync_blog_roll:{identity.acct}") as t:
        m = client_from_identity(identity)

        try:
            home_statuses = m.timeline_home(limit=100)
            t.rows_fetched = len(home_statuses)

            rows = [
                {
                    "account_data": s["account"],
                    "last_status_at": to_naive_utc(s["created_at"]),
                }
                for s in home_statuses
            ]

            async with async_session() as session:
                await bulk_upsert_accounts(session, meta_id, identity.id, rows)
                await session.commit()
                t.rows_written = len(rows)

            # Recompute post stats for all accounts seen in this identity's cached posts.
            # Single GROUP BY query; results written back to cached_accounts.
            async with async_session() as session:
                stats_rows = (
                    await session.execute(
                        select(
                            CachedPost.author_id,
                            func.count(CachedPost.id).label("total"),  # pylint: disable=not-callable
                            func.sum(func.cast(CachedPost.is_reply, Integer)).label("replies"),  # pylint: disable=not-callable
                        )
                        .where(
                            and_(
                                CachedPost.meta_account_id == meta_id,
                                CachedPost.fetched_by_identity_id == identity.id,
                            )
                        )
                        .group_by(CachedPost.author_id)
                    )
                ).all()

                if stats_rows:
                    author_ids = [row.author_id for row in stats_rows]
                    accounts_res = await session.execute(
                        select(CachedAccount).where(
                            and_(
                                CachedAccount.meta_account_id == meta_id,
                                CachedAccount.mastodon_identity_id == identity.id,
                                CachedAccount.id.in_(author_ids),
                            )
                        )
                    )
                    accounts_by_id = {a.id: a for a in accounts_res.scalars().all()}

                    for row in stats_rows:
                        acc = accounts_by_id.get(row.author_id)
                        if acc:
                            acc.cached_post_count = row.total or 0
                            acc.cached_reply_count = row.replies or 0

                    await session.commit()

        except Exception as e:
            logger.error(e)
            logger.error("Failed to sync blog roll for %s: %s", identity.acct, e)
            raise


async def sync_user_timeline_for_identity(
    meta_id: int,
    identity: MastodonIdentity,
    acct: str | None = None,
    force: bool = False,
    cooldown_minutes: int = 15,
    deep: bool = False,
    max_pages: int | None = None,
    rate_budget=None,
) -> dict:
    """Syncs posts for a specific identity and optional target account.

    When deep=True, walks all available pages via max_id pagination instead of
    fetching a single page of 200.  max_pages caps the walk; rate_budget
    (a catchup.RateBudget) is shared across concurrent deep fetches.
    """
    target_acct_desc = acct if acct else "self"
    sync_key = f"timeline:{meta_id}:{identity.id}:{target_acct_desc}"

    last_run = await get_last_sync(sync_key)
    if (
        not force
        and last_run
        and (datetime.utcnow() - last_run) < timedelta(minutes=cooldown_minutes)
    ):
        return {"status": "skipped"}

    stage_name = f"sync_timeline:{identity.acct}:{target_acct_desc}"
    async with sync_stage(stage_name) as t:
        m = client_from_identity(identity)

        try:
            if acct:
                s_res = m.account_search(acct, limit=1)
                if not s_res:
                    return {"status": "not_found"}
                target_account = s_res[0]
                target_id = target_account["id"]
            else:
                target_account = m.account_verify_credentials()
                target_id = target_account["id"]

            total_fetched = 0
            total_new = 0
            total_updated = 0

            if deep:
                from mastodon_is_my_blog.catchup import (
                    deep_fetch_user_timeline,
                    get_stop_at_id,
                )

                stop_at_id = await get_stop_at_id(
                    meta_id, identity.id, target_account["acct"]
                )

                async for page in deep_fetch_user_timeline(
                    m,
                    str(target_id),
                    stop_at_id=stop_at_id,
                    max_pages=max_pages,
                    rate_budget=rate_budget,
                ):
                    total_fetched += len(page)
                    async with async_session() as session:
                        await bulk_upsert_accounts(
                            session,
                            meta_id,
                            identity.id,
                            [{"account_data": target_account}],
                        )
                        new_count, updated_count = await bulk_upsert_posts(
                            session, meta_id, identity.id, page
                        )
                        await session.commit()
                    total_new += new_count
                    total_updated += updated_count
            else:
                statuses = m.account_statuses(target_id, limit=200)
                total_fetched = len(statuses)

                async with async_session() as session:
                    await bulk_upsert_accounts(
                        session,
                        meta_id,
                        identity.id,
                        [{"account_data": target_account}],
                    )
                    total_new, total_updated = await bulk_upsert_posts(
                        session, meta_id, identity.id, statuses
                    )
                    await session.commit()

            await update_last_sync(sync_key)
            t.rows_fetched = total_fetched
            t.rows_written = total_new + total_updated
            t.rows_skipped = 0
            t.extra["new"] = total_new
            t.extra["updated"] = total_updated
            return {"status": "success", "count": total_fetched}

        except Exception as e:
            logger.error(e)
            logger.error("Sync error %s: %s", sync_key, e)
            return {"status": "error", "msg": str(e)}


async def sync_accounts_friends_followers() -> None:
    """Legacy wrapper for backward compatibility."""
    token = await get_token()
    if not token:
        logger.warning("No token")
        return

    # Get default meta and identity
    async with async_session() as session:
        stmt = select(MetaAccount).where(MetaAccount.username == "default")
        meta = (await session.execute(stmt)).scalar_one_or_none()
        if not meta:
            return

        stmt = (
            select(MastodonIdentity)
            .where(MastodonIdentity.meta_account_id == meta.id)
            .limit(1)
        )
        identity = (await session.execute(stmt)).scalar_one_or_none()
        if not identity:
            return

    await sync_friends_for_identity(meta.id, identity)
    await update_last_sync("accounts")


async def sync_blog_roll_activity() -> None:
    """Legacy wrapper for backward compatibility."""
    async with async_session() as session:
        stmt = select(MetaAccount).where(MetaAccount.username == "default")
        meta = (await session.execute(stmt)).scalar_one_or_none()
        if not meta:
            return

        stmt = (
            select(MastodonIdentity)
            .where(MastodonIdentity.meta_account_id == meta.id)
            .limit(1)
        )
        identity = (await session.execute(stmt)).scalar_one_or_none()
        if not identity:
            return

    await sync_blog_roll_for_identity(meta.id, identity)


async def sync_user_timeline(
    acct: str | None = None,
    _acct_id: str | None = None,
    force: bool = False,
    _cooldown_minutes: int = 15,
) -> dict:
    """Legacy wrapper: Syncs posts for a specific user to Default Meta Account."""
    if acct == "everyone":
        return {"status": "skipped", "reason": "virtual_user"}

    async with async_session() as session:
        # Get default meta
        stmt = select(MetaAccount).where(MetaAccount.username == "default")
        meta = (await session.execute(stmt)).scalar_one_or_none()
        if not meta:
            raise HTTPException(500, "Default meta account missing")

        # Get first identity
        stmt = (
            select(MastodonIdentity)
            .where(MastodonIdentity.meta_account_id == meta.id)
            .limit(1)
        )
        identity = (await session.execute(stmt)).scalar_one_or_none()
        if not identity:
            raise HTTPException(500, "No identity found")

    return await sync_user_timeline_for_identity(
        meta_id=meta.id, identity=identity, acct=acct, force=force
    )


async def get_counts_optimized(
    session: AsyncSession, meta_id: int, identity_id: int, user: str | None = None
) -> dict[str, int | str]:
    """
    Optimized count query returns { "filter": {"total": X, "unseen": Y} }
    """

    # Build base conditions
    base_conditions = [
        CachedPost.meta_account_id == meta_id,
        CachedPost.fetched_by_identity_id == identity_id,
        CachedPost.content_hub_only.is_(False),
    ]

    if user:
        base_conditions.append(CachedPost.author_acct == user)

    # Helper for conditional aggregation
    def filter_count(condition, label: str):
        total = func.sum(func.cast(condition, Integer)).label(f"total_{label}")  # pylint: disable=not-callable
        unseen = func.sum(
            func.cast(and_(condition, SeenPost.post_id.is_(None)), Integer)  # pylint: disable=not-callable
        ).label(f"unseen_{label}")
        return total, unseen

    # Define our filters matching the UI categories
    f_shorts = and_(
        CachedPost.is_reply.is_(False),
        CachedPost.is_reblog.is_(False),
        CachedPost.has_media.is_(False),
        CachedPost.has_link.is_(False),
        func.length(CachedPost.content) < 500,
    )
    # Storm count approximation: roots that are long enough to qualify.
    # Self-reply chains can't be counted efficiently in SQL; length >= 500 catches most.
    f_storms = and_(
        CachedPost.is_reblog.is_(False),
        CachedPost.in_reply_to_id.is_(None),
        CachedPost.has_link.is_(False),
        func.length(CachedPost.content) >= 500,
    )
    f_news = CachedPost.has_news.is_(True)
    f_software = CachedPost.has_tech.is_(True)
    f_links = CachedPost.has_link.is_(True)
    f_pics = CachedPost.has_media.is_(True)
    f_vids = CachedPost.has_video.is_(True)
    f_discussions = CachedPost.is_reply.is_(True)

    # Build the massive select
    sel_args = []
    for cond, name in [
        (True, "everyone"),  # 'True' acts as a placeholder for all posts
        (f_shorts, "shorts"),
        (f_storms, "storms"),
        (f_news, "news"),
        (f_software, "software"),
        (f_links, "links"),
        (f_pics, "pictures"),
        (f_vids, "videos"),
        (f_discussions, "discussions"),
    ]:
        sel_args.extend(filter_count(cond, name))

    query = (
        select(*sel_args)
        .select_from(
            outerjoin(
                CachedPost,
                SeenPost,
                and_(
                    CachedPost.id == SeenPost.post_id,
                    SeenPost.meta_account_id == meta_id,
                ),
            )
        )
        .where(and_(*base_conditions))
    )

    result = await session.execute(query)
    row = result.first()

    # Format the response for the frontend
    keys = [
        "everyone",
        "shorts",
        "storms",
        "news",
        "software",
        "links",
        "pictures",
        "videos",
        "discussions",
    ]
    stats = {"user": user or "all"}

    for key in keys:
        stats[key] = {
            "total": getattr(row, f"total_{key}") or 0,
            "unseen": getattr(row, f"unseen_{key}") or 0,
        }

    return stats
