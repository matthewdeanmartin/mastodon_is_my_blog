from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from mastodon_is_my_blog import identity_verifier
from mastodon_is_my_blog.store import MastodonIdentity
from test.conftest import make_identity


@pytest.mark.asyncio
async def test_verify_identity_returns_false_when_identity_missing(
    patch_async_session,
) -> None:
    patch_async_session(identity_verifier)

    assert await identity_verifier.verify_identity(999) is False


@pytest.mark.asyncio
async def test_verify_identity_returns_false_without_access_token(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(identity_verifier)
    db_session.add(make_identity(access_token=""))
    await db_session.commit()

    assert await identity_verifier.verify_identity(1) is False


@pytest.mark.asyncio
async def test_verify_identity_updates_verified_account_fields(
    db_session,
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(identity_verifier)
    db_session.add(make_identity(acct="unknown@unknown", account_id="0"))
    await db_session.commit()

    client = MagicMock()
    client.account_verify_credentials.return_value = {"acct": "verified@example.social", "id": 42}

    with patch.object(identity_verifier, "client_from_identity", return_value=client):
        result = await identity_verifier.verify_identity(1)

    assert result is True

    async with db_session_factory() as session:
        stored = (
            await session.execute(
                select(MastodonIdentity).where(MastodonIdentity.id == 1)
            )
        ).scalar_one()

    assert stored.acct == "verified@example.social"
    assert stored.account_id == "42"


@pytest.mark.asyncio
async def test_verify_identity_returns_false_when_client_verification_fails(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(identity_verifier)
    db_session.add(make_identity())
    await db_session.commit()

    client = MagicMock()
    client.account_verify_credentials.side_effect = RuntimeError("boom")

    with patch.object(identity_verifier, "client_from_identity", return_value=client):
        result = await identity_verifier.verify_identity(1)

    assert result is False


@pytest.mark.asyncio
async def test_verify_all_identities_returns_per_identity_results(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(identity_verifier)
    db_session.add_all(
        [
            make_identity(identity_id=1, acct="first@example.social"),
            make_identity(identity_id=2, acct="second@example.social"),
        ]
    )
    await db_session.commit()

    verify_mock = AsyncMock(side_effect=[True, False])
    with patch.object(identity_verifier, "verify_identity", verify_mock):
        result = await identity_verifier.verify_all_identities()

    assert result == {1: True, 2: False}
