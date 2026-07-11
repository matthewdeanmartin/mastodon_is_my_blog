"""
Syncs notifications and stores them in the database for flexible querying.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import and_, func, select

from mastodon_is_my_blog.datetime_helpers import to_naive_utc, utc_now
from mastodon_is_my_blog.mastodon_apis.masto_client import client_from_identity
from mastodon_is_my_blog.queries import (
    bulk_upsert_accounts,
    sync_user_timeline_for_identity,
)
from mastodon_is_my_blog.store import (
    CachedAccount,
    CachedNotification,
    MastodonIdentity,
    async_session,
)
from mastodon_is_my_blog.utils.perf import sync_stage

logger = logging.getLogger(__name__)


async def persist_notifications(
    meta_id: int,
    identity: MastodonIdentity,
    notifications: list[dict],
    stats: dict[str, int],
) -> tuple[set[str], int]:
    """
    Persist a single page of notifications. Upserts notification rows and
    accounts seen in them. Returns (account_ids_seen, new_notification_count).

    Accounts are upserted without follow-state overrides, so non-followed
    reposters land in cached_accounts with is_following=False — required for
    the Readers blogroll filter.
    """
    synced_account_ids: set[str] = set()
    account_rows: list[dict] = []
    new_notif_count = 0

    async with async_session() as session:
        for notif in notifications:
            stats["total"] += 1
            notif_id = str(notif["id"])
            notif_type = notif["type"]
            account_data = notif["account"]
            account_id = str(account_data["id"])
            created_at = to_naive_utc(notif.get("created_at"))

            status_id = None
            if notif.get("status"):
                status_id = str(notif["status"]["id"])

            if notif_type == "mention":
                stats["mentions"] += 1
            elif notif_type == "favourite":
                stats["favorites"] += 1
            elif notif_type == "reblog":
                stats["reblogs"] += 1
            elif notif_type == "status":
                stats["replies"] += 1
            elif notif_type == "follow":
                stats["follows"] += 1

            stmt = select(CachedNotification).where(
                and_(
                    CachedNotification.id == notif_id,
                    CachedNotification.meta_account_id == meta_id,
                    CachedNotification.identity_id == identity.id,
                )
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()

            if not existing:
                new_notif = CachedNotification(
                    id=notif_id,
                    meta_account_id=meta_id,
                    identity_id=identity.id,
                    type=notif_type,
                    created_at=created_at,
                    account_id=account_id,
                    account_acct=account_data["acct"],
                    status_id=status_id,
                )
                session.add(new_notif)
                new_notif_count += 1

            if account_id not in synced_account_ids:
                account_rows.append({"account_data": account_data})
                synced_account_ids.add(account_id)
                stats["accounts_synced"] += 1

        if account_rows:
            await bulk_upsert_accounts(session, meta_id, identity.id, account_rows)

        await session.commit()

    return synced_account_ids, new_notif_count


async def sync_all_notifications_for_identity(
    meta_id: int,
    identity: MastodonIdentity,
    on_progress=None,
    cancelled=None,
    inter_page_delay: float = 0.3,
    max_pages: int | None = None,
) -> dict[str, int]:
    """
    Paginated backfill of the identity's full notification history.

    Walks Mastodon.py fetch_next() until exhausted. Upserts notification rows
    and their originating accounts so the Readers blogroll filter surfaces
    every historical reposter, not just the last 80 interactions.
    """
    async with sync_stage(f"sync_all_notifications:{identity.acct}") as t:
        m = client_from_identity(identity)
        stats: dict[str, int] = {
            "total": 0,
            "mentions": 0,
            "replies": 0,
            "favorites": 0,
            "reblogs": 0,
            "follows": 0,
            "accounts_synced": 0,
            "timelines_synced": 0,
        }
        pages = 0

        try:
            page = await asyncio.to_thread(m.notifications, limit=80)
            while page:
                if cancelled is not None and cancelled():
                    break
                await persist_notifications(meta_id, identity, page, stats)
                pages += 1
                if on_progress is not None:
                    on_progress(stats["total"], None, f"page {pages}")
                if max_pages is not None and pages >= max_pages:
                    break
                next_page = await asyncio.to_thread(m.fetch_next, page)
                if not next_page:
                    break
                page = next_page
                await asyncio.sleep(inter_page_delay)

            t.rows_fetched = stats["total"]
            t.rows_written = stats["total"]
            t.extra = dict(stats)
            logger.info(
                "Deep notification sync for %s: %d notifications across %d pages",
                identity.acct,
                stats["total"],
                pages,
            )
            return stats
        except Exception as e:
            logger.error("sync_all_notifications failed for %s: %s", identity.acct, e)
            raise


async def sync_notifications_for_identity(meta_id: int, identity: MastodonIdentity) -> dict[str, int]:
    """
    Fetches notifications and stores them in the database.
    Also syncs accounts and timelines for mutual followers who interacted.
    """
    async with sync_stage(f"sync_notifications:{identity.acct}") as t:
        m = client_from_identity(identity)

        try:
            # Fetch notifications (last 80 interactions)
            notifications = m.notifications(limit=80)
            t.rows_fetched = len(notifications)

            stats: dict[str, int] = {
                "total": 0,
                "mentions": 0,
                "replies": 0,
                "favorites": 0,
                "reblogs": 0,
                "follows": 0,
                "accounts_synced": 0,
                "timelines_synced": 0,
            }

            synced_account_ids, new_notif_count = await persist_notifications(meta_id, identity, notifications, stats)
            t.rows_written = new_notif_count

            # Second-hop: sync timelines for top-5 mutuals by recent notification count.
            # 60-min cooldown keeps notification sync from amplifying into many API calls.
            SECOND_HOP_LIMIT = 5
            SECOND_HOP_COOLDOWN = 60
            cutoff = utc_now() - timedelta(days=30)

            async with async_session() as session:
                # Rank mutuals among the accounts we just saw by recent notification count.
                top_mutuals_stmt = (
                    select(CachedAccount)
                    .join(
                        CachedNotification,
                        and_(
                            CachedNotification.account_id == CachedAccount.id,
                            CachedNotification.meta_account_id == meta_id,
                            CachedNotification.identity_id == identity.id,
                            CachedNotification.created_at >= cutoff,
                        ),
                    )
                    .where(
                        CachedAccount.id.in_(synced_account_ids),
                        CachedAccount.meta_account_id == meta_id,
                        CachedAccount.mastodon_identity_id == identity.id,
                        CachedAccount.is_following.is_(True),
                        CachedAccount.is_followed_by.is_(True),
                    )
                    .group_by(CachedAccount.id)
                    .order_by(func.count(CachedNotification.id).desc())  # pylint: disable=not-callable
                    .limit(SECOND_HOP_LIMIT)
                )
                top_mutuals = (await session.execute(top_mutuals_stmt)).scalars().all()

            for mutual in top_mutuals:
                try:
                    await sync_user_timeline_for_identity(
                        meta_id=meta_id,
                        identity=identity,
                        acct=mutual.acct,
                        force=False,
                        cooldown_minutes=SECOND_HOP_COOLDOWN,
                    )
                    stats["timelines_synced"] += 1
                except Exception as e:
                    logger.warning("Failed to sync timeline for %s: %s", mutual.acct, e)

            t.extra = dict(stats)

            logger.info(
                "Notification sync for %s: %d notifications, %d accounts synced, %d timelines synced",
                identity.acct,
                stats["total"],
                stats["accounts_synced"],
                stats["timelines_synced"],
            )

            return stats

        except Exception as e:
            logger.error("Failed to sync notifications for %s: %s", identity.acct, e)
            raise
