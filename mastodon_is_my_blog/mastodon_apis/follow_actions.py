# mastodon_is_my_blog/mastodon_apis/follow_actions.py
"""Follow/unfollow write actions against the Mastodon API."""
import asyncio
import logging

from fastapi import HTTPException
from sqlalchemy import and_, select

from mastodon_is_my_blog.mastodon_apis.masto_client import client_from_identity
from mastodon_is_my_blog.store import (
    CachedAccount,
    MastodonIdentity,
    async_session,
)

logger = logging.getLogger(__name__)


async def follow_account(meta_id: int, identity: MastodonIdentity, acct: str) -> dict:
    """Resolve acct to a remote id, follow them, update local cache."""
    m = client_from_identity(identity)

    try:
        results = await asyncio.to_thread(m.account_search, acct, limit=1)
    except Exception as e:
        logger.error("account_search failed for %s: %s", acct, e)
        raise HTTPException(502, f"Mastodon API error: {e}") from e

    if not results:
        raise HTTPException(404, f"Account {acct!r} not found via Mastodon search")

    remote_id = str(results[0]["id"])

    try:
        await asyncio.to_thread(m.account_follow, remote_id)
    except Exception as e:
        logger.error("account_follow failed for %s: %s", acct, e)
        raise HTTPException(502, f"Mastodon API error: {e}") from e

    async with async_session() as session:
        stmt = select(CachedAccount).where(
            and_(
                CachedAccount.id == remote_id,
                CachedAccount.meta_account_id == meta_id,
                CachedAccount.mastodon_identity_id == identity.id,
            )
        )
        ca = (await session.execute(stmt)).scalar_one_or_none()
        if ca:
            ca.is_following = True
            await session.commit()

    return {"followed": True, "acct": acct}


async def unfollow_account(
    meta_id: int, identity: MastodonIdentity, acct: str
) -> dict:
    """Resolve acct to a remote id, unfollow them, update local cache."""
    m = client_from_identity(identity)

    try:
        results = await asyncio.to_thread(m.account_search, acct, limit=1)
    except Exception as e:
        logger.error("account_search failed for %s: %s", acct, e)
        raise HTTPException(502, f"Mastodon API error: {e}") from e

    if not results:
        raise HTTPException(404, f"Account {acct!r} not found via Mastodon search")

    remote_id = str(results[0]["id"])

    try:
        await asyncio.to_thread(m.account_unfollow, remote_id)
    except Exception as e:
        logger.error("account_unfollow failed for %s: %s", acct, e)
        raise HTTPException(502, f"Mastodon API error: {e}") from e

    async with async_session() as session:
        stmt = select(CachedAccount).where(
            and_(
                CachedAccount.id == remote_id,
                CachedAccount.meta_account_id == meta_id,
                CachedAccount.mastodon_identity_id == identity.id,
            )
        )
        ca = (await session.execute(stmt)).scalar_one_or_none()
        if ca:
            ca.is_following = False
            await session.commit()

    return {"unfollowed": True, "acct": acct}
