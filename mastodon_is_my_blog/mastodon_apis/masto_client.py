# mastodon_is_my_blog/masto_client.py
"""
Factory functions for creating Mastodon API clients.
"""
import logging
import os

import dotenv
from mastodon import Mastodon
from sqlalchemy import select

from mastodon_is_my_blog.mastodon_apis.masto_client_timed import TimedMastodonClient
from mastodon_is_my_blog.store import (
    MastodonIdentity,
    async_session,
    get_default_identity,
)
from mastodon_is_my_blog.utils.settings_loader import resolve_identity_config

dotenv.load_dotenv()

logger = logging.getLogger(__name__)
PERF = True


def client(
    *,
    base_url: str = os.environ.get("MASTODON_API_BASE_URL", ""),
    client_id: str = os.environ.get("MASTODON_CLIENT_ID", ""),
    client_secret: str = os.environ.get("MASTODON_CLIENT_SECRET", ""),
    access_token: str | None = os.environ.get("MASTODON_ACCESS_TOKEN"),
) -> Mastodon | TimedMastodonClient:
    """
    Creates a Mastodon client with direct credentials.
    """
    if not base_url:
        raise ValueError("Missing required config: base_url")
    if not client_id:
        raise ValueError("Missing required config: client_id")
    if not client_secret:
        raise ValueError("Missing required config: client_secret")

    if not base_url.startswith("http"):
        logger.error("Invalid base_url format: %s", base_url)
        raise ValueError("base_url must start with http or https")

    final_base_url = base_url.rstrip("/")

    if PERF:
        return TimedMastodonClient(
            api_base_url=final_base_url,
            client_id=client_id,
            client_secret=client_secret,
            access_token=access_token,
        )

    return Mastodon(
        api_base_url=final_base_url,
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
    )


def client_from_identity(
    identity: "MastodonIdentity",
) -> Mastodon | TimedMastodonClient:
    """
    Creates a Mastodon client from a MastodonIdentity object.
    This is the preferred way to instantiate clients.
    """
    if not identity:
        raise ValueError("Cannot create client: Identity is None")

    configured_identity = resolve_identity_config(
        identity.config_name,
        base_url=identity.api_base_url,
    )

    client_id = configured_identity.client_id if configured_identity else identity.client_id
    client_secret = (
        configured_identity.client_secret
        if configured_identity
        else identity.client_secret
    )
    access_token = (
        configured_identity.access_token
        if configured_identity
        else identity.access_token
    )
    base_url = configured_identity.base_url if configured_identity else identity.api_base_url

    return client(
        base_url=base_url,
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
    )


def identity_has_access_token(identity: "MastodonIdentity") -> bool:
    configured_identity = resolve_identity_config(
        getattr(identity, "config_name", None),
        base_url=getattr(identity, "api_base_url", None),
    )
    if configured_identity and configured_identity.access_token:
        return True
    return bool(getattr(identity, "access_token", ""))


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
            raise ValueError(f"Identity ID {identity_id} not found in database")

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
    Strictly relies on the database being bootstrapped.
    """

    identity = await get_default_identity()
    if not identity:
        # We do not fallback to env vars or magic here.
        # If the DB isn't bootstrapped, the app is broken.
        raise ValueError(
            "Default identity not found. Ensure .env is configured and app has bootstrapped."
        )

    return client_from_identity(identity)
