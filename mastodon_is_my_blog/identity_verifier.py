# mastodon_is_my_blog/identity_verifier.py
"""
Helper to verify and update MastodonIdentity records with actual account info.
This is needed because identities loaded from .env don't have acct/account_id initially.
"""
import logging

from sqlalchemy import select

from mastodon_is_my_blog.mastodon_apis.masto_client import client
from mastodon_is_my_blog.store import MastodonIdentity, async_session

logger = logging.getLogger(__name__)


async def verify_identity(identity_id: int) -> bool:
    """
    Verifies an identity by calling Mastodon API and updating acct/account_id.
    Returns True if successful, False otherwise.
    """
    async with async_session() as session:
        stmt = select(MastodonIdentity).where(MastodonIdentity.id == identity_id)
        identity = (await session.execute(stmt)).scalar_one_or_none()

        if not identity:
            logger.error("Identity %s not found", identity_id)
            return False

        if not identity.access_token:
            logger.error("Identity %s has no access token", identity_id)
            return False

        try:
            m = client(
                base_url=identity.api_base_url,
                client_id=identity.client_id,
                client_secret=identity.client_secret,
                access_token=identity.access_token,
            )
            me = m.account_verify_credentials()

            # Update the identity with real account info
            identity.acct = me["acct"]
            identity.account_id = str(me["id"])

            await session.commit()
            logger.info("Verified identity {identity_id}: %s", me['acct'])
            return True

        except Exception as e:
            logger.error("Identity verification failed: %s", e)
            logger.error("Failed to verify identity {identity_id}: %s", e)
            return False


async def verify_all_identities() -> dict[int, bool]:
    """
    Verifies all identities in the database.
    Returns dict mapping identity_id -> success boolean.
    """
    async with async_session() as session:
        stmt = select(MastodonIdentity)
        result = await session.execute(stmt)
        identities = result.scalars().all()

    results = {}
    for identity in identities:
        results[identity.id] = await verify_identity(identity.id)

    return results
