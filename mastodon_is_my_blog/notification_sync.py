"""
Syncs notifications and stores them in the database for flexible querying.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import and_, select

from mastodon_is_my_blog.mastodon_apis.masto_client import client_from_identity
from mastodon_is_my_blog.queries import _upsert_account, sync_user_timeline_for_identity
from mastodon_is_my_blog.store import (
    CachedAccount,
    CachedNotification,
    MastodonIdentity,
    async_session,
)

logger = logging.getLogger(__name__)


def to_naive_utc(dt: datetime | None) -> datetime | None:
    """Convert datetime to naive UTC."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def sync_notifications_for_identity(
    meta_id: int, identity: MastodonIdentity
) -> dict[str, int]:
    """
    Fetches notifications and stores them in the database.
    Also syncs accounts and timelines for mutual followers who interacted.
    """
    m = client_from_identity(identity)

    try:
        # Fetch notifications (last 80 interactions)
        notifications = m.notifications(limit=80)

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

        synced_account_ids: set[str] = set()

        async with async_session() as session:
            for notif in notifications:
                stats["total"] += 1
                notif_id = str(notif["id"])
                notif_type = notif["type"]
                account_data = notif["account"]
                account_id = str(account_data["id"])
                created_at = to_naive_utc(notif.get("created_at"))

                # Get status ID if present
                status_id = None
                if notif.get("status"):
                    status_id = str(notif["status"]["id"])

                # Track by type
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

                # Check if notification already exists
                stmt = select(CachedNotification).where(
                    and_(
                        CachedNotification.id == notif_id,
                        CachedNotification.meta_account_id == meta_id,
                        CachedNotification.identity_id == identity.id,
                    )
                )
                existing = (await session.execute(stmt)).scalar_one_or_none()

                if not existing:
                    # Create new notification
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

                # Upsert the account (for blog roll display)
                if account_id not in synced_account_ids:
                    await _upsert_account(session, meta_id, identity.id, account_data)
                    synced_account_ids.add(account_id)
                    stats["accounts_synced"] += 1

            await session.commit()

        # Now sync timelines for mutual followers who interacted
        async with async_session() as session:
            for account_id in synced_account_ids:
                stmt = select(CachedAccount).where(
                    and_(
                        CachedAccount.id == account_id,
                        CachedAccount.meta_account_id == meta_id,
                        CachedAccount.mastodon_identity_id == identity.id,
                        CachedAccount.is_following == True,
                        CachedAccount.is_followed_by == True,
                    )
                )
                mutual = (await session.execute(stmt)).scalar_one_or_none()

                if mutual:
                    try:
                        await sync_user_timeline_for_identity(
                            meta_id=meta_id,
                            identity=identity,
                            acct=mutual.acct,
                            force=False,
                        )
                        stats["timelines_synced"] += 1
                    except Exception as e:
                        logger.warning(
                            f"Failed to sync timeline for {mutual.acct}: {e}"
                        )

        logger.info(
            f"Notification sync for {identity.acct}: {stats['total']} notifications, "
            f"{stats['accounts_synced']} accounts synced, "
            f"{stats['timelines_synced']} timelines synced"
        )

        return stats

    except Exception as e:
        logger.error(f"Failed to sync notifications for {identity.acct}: {e}")
        return {"error": str(e), "total": 0}
