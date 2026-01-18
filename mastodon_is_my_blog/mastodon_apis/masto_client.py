# mastodon_is_my_blog/masto_client.py
"""
Factory functions for creating Mastodon API clients.

Supports multiple patterns:
1. Direct credentials (api_base_url, client_id, client_secret, access_token)
2. MastodonIdentity object
3. Identity ID lookup
4. Legacy token-based (for backwards compatibility)
"""
import logging
import os
from typing import Optional

import dotenv
from mastodon import Mastodon
from sqlalchemy import select

from mastodon_is_my_blog.mastodon_apis.masto_client_timed import TimedMastodonClient
from mastodon_is_my_blog.store import (
    MastodonIdentity,
    async_session,
    get_default_identity,
)

dotenv.load_dotenv()

logger = logging.getLogger(__name__)
PERF = True


def client(
    base_url: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Mastodon | TimedMastodonClient:
    """
    Creates a Mastodon client with direct credentials.

    If no arguments provided, falls back to environment variables:
    - MASTODON_BASE_URL
    - MASTODON_CLIENT_ID
    - MASTODON_CLIENT_SECRET
    - MASTODON_ACCESS_TOKEN
    """
    # Fall back to environment if not provided
    final_base_url = base_url or os.environ.get(
        "MASTODON_BASE_URL", "https://mastodon.social"
    )
    final_client_id = client_id or os.environ.get("MASTODON_CLIENT_ID")
    final_client_secret = client_secret or os.environ.get("MASTODON_CLIENT_SECRET")
    final_access_token = access_token or os.environ.get("MASTODON_ACCESS_TOKEN")

    if not final_client_id or not final_client_secret:
        raise ValueError("Missing required Mastodon credentials")

    if PERF:
        return TimedMastodonClient(
            api_base_url=final_base_url.rstrip("/"),
            client_id=final_client_id,
            client_secret=final_client_secret,
            access_token=final_access_token,
        )

    return Mastodon(
        api_base_url=final_base_url.rstrip("/"),
        client_id=final_client_id,
        client_secret=final_client_secret,
        access_token=final_access_token,
    )


def client_from_identity(
    identity: "MastodonIdentity",
) -> Mastodon | TimedMastodonClient:
    """
    Creates a Mastodon client from a MastodonIdentity object.

    Args:
        identity: MastodonIdentity database object

    Returns:
        Configured Mastodon client
    """
    return client(
        base_url=identity.api_base_url,
        client_id=identity.client_id,
        client_secret=identity.client_secret,
        access_token=identity.access_token,
    )


async def client_from_identity_id(identity_id: int) -> Mastodon | TimedMastodonClient:
    """
    Creates a Mastodon client by looking up an identity by ID.

    Args:
        identity_id: Database ID of the MastodonIdentity

    Returns:
        Configured Mastodon client

    Raises:
        ValueError: If identity not found
    """

    async with async_session() as session:
        stmt = select(MastodonIdentity).where(MastodonIdentity.id == identity_id)
        identity = (await session.execute(stmt)).scalar_one_or_none()

        if not identity:
            raise ValueError(f"Identity {identity_id} not found")

        return client_from_identity(identity)


async def client_from_meta_account(
    meta_account_id: int, identity_index: int = 0
) -> Mastodon | TimedMastodonClient:
    """
    Creates a client for a specific meta account.

    Args:
        meta_account_id: Database ID of the MetaAccount
        identity_index: Which identity to use (default: first one)

    Returns:
        Configured Mastodon client

    Raises:
        ValueError: If meta account has no identities
    """

    async with async_session() as session:
        stmt = (
            select(MastodonIdentity)
            .where(MastodonIdentity.meta_account_id == meta_account_id)
            .offset(identity_index)
            .limit(1)
        )
        identity = (await session.execute(stmt)).scalar_one_or_none()

        if not identity:
            raise ValueError(
                f"No identity found for meta_account {meta_account_id} "
                f"at index {identity_index}"
            )

        return client_from_identity(identity)


async def get_default_client() -> Mastodon | TimedMastodonClient:
    """
    Gets a client for the default meta account's first identity.
    Falls back to environment variables if no default identity exists.

    Returns:
        Configured Mastodon client
    """

    identity = await get_default_identity()
    if identity:
        return client_from_identity(identity)

    # Fall back to environment-based client
    logger.warning("No default identity found, using environment variables")
    return client()
