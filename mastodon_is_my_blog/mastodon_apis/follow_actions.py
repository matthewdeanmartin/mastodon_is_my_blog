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


def acct_matches(requested: str, found: str) -> bool:
    """True if a search result acct is the account the caller asked for.

    Mastodon search is fuzzy and returns the closest match, so an exact
    (case-insensitive) comparison is required before acting on the result.
    A local account may be reported without its domain, so when either side
    lacks a domain only the local parts are compared.
    """
    req = requested.strip().lstrip("@").lower()
    got = found.strip().lstrip("@").lower()
    if req == got:
        return True
    if "@" not in req or "@" not in got:
        return req.split("@")[0] == got.split("@")[0]
    return False


async def resolve_remote_id(m, acct: str) -> str:
    """Resolve acct to its remote account id, verifying the match."""
    try:
        results = await asyncio.to_thread(m.account_search, acct, limit=1)
    except Exception as e:
        logger.error("account_search failed for %s: %s", acct, e)
        raise HTTPException(502, f"Mastodon API error: {e}") from e

    if not results:
        raise HTTPException(404, f"Account {acct!r} not found via Mastodon search")

    found_acct = str(results[0].get("acct", ""))
    if not acct_matches(acct, found_acct):
        raise HTTPException(
            404,
            f"Account {acct!r} not found via Mastodon search "
            f"(closest match was {found_acct!r})",
        )

    return str(results[0]["id"])


async def set_cached_following(
    meta_id: int, identity: MastodonIdentity, remote_id: str, is_following: bool
) -> None:
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
            ca.is_following = is_following
            await session.commit()


async def follow_account(meta_id: int, identity: MastodonIdentity, acct: str) -> dict:
    """Resolve acct to a remote id, follow them, update local cache."""
    m = client_from_identity(identity)
    remote_id = await resolve_remote_id(m, acct)

    try:
        await asyncio.to_thread(m.account_follow, remote_id)
    except Exception as e:
        logger.error("account_follow failed for %s: %s", acct, e)
        raise HTTPException(502, f"Mastodon API error: {e}") from e

    await set_cached_following(meta_id, identity, remote_id, True)
    return {"followed": True, "acct": acct}


async def unfollow_account(meta_id: int, identity: MastodonIdentity, acct: str) -> dict:
    """Resolve acct to a remote id, unfollow them, update local cache."""
    m = client_from_identity(identity)
    remote_id = await resolve_remote_id(m, acct)

    try:
        await asyncio.to_thread(m.account_unfollow, remote_id)
    except Exception as e:
        logger.error("account_unfollow failed for %s: %s", acct, e)
        raise HTTPException(502, f"Mastodon API error: {e}") from e

    await set_cached_following(meta_id, identity, remote_id, False)
    return {"unfollowed": True, "acct": acct}
