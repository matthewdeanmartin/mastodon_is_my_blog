"""Encryption at rest for credential columns (secret_columns.py)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import StatementError

from mastodon_is_my_blog.secret_columns import ENCRYPTED_PREFIX, generate_key
from mastodon_is_my_blog.store import MastodonIdentity

from test.conftest import make_identity, make_meta_account


async def seed_identity(session, access_token: str = "super-secret-token"):
    session.add(make_meta_account())
    session.add(make_identity(access_token=access_token))
    await session.commit()


async def raw_access_token(session) -> str:
    result = await session.execute(
        text("SELECT access_token FROM mastodon_identities WHERE id = 1")
    )
    return result.scalar_one()


async def orm_access_token(session) -> str:
    identity = await session.get(MastodonIdentity, 1)
    return identity.access_token


@pytest.mark.asyncio
async def test_key_set_encrypts_on_disk_and_decrypts_via_orm(
    monkeypatch, db_session_factory
):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    async with db_session_factory() as session:
        await seed_identity(session)
        stored = await raw_access_token(session)
        assert stored.startswith(ENCRYPTED_PREFIX)
        assert "super-secret-token" not in stored

    async with db_session_factory() as session:
        assert await orm_access_token(session) == "super-secret-token"


@pytest.mark.asyncio
async def test_no_key_local_mode_is_passthrough(monkeypatch, db_session_factory):
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("MIMB_MODE", raising=False)
    async with db_session_factory() as session:
        await seed_identity(session)
        assert await raw_access_token(session) == "super-secret-token"
        assert await orm_access_token(session) == "super-secret-token"


@pytest.mark.asyncio
async def test_legacy_plaintext_still_reads_after_key_is_introduced(
    monkeypatch, db_session_factory
):
    # Write plaintext (pre-key install)...
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("MIMB_MODE", raising=False)
    async with db_session_factory() as session:
        await seed_identity(session, access_token="legacy-plaintext")

    # ...then turn encryption on: old rows must keep reading.
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    async with db_session_factory() as session:
        assert await orm_access_token(session) == "legacy-plaintext"


@pytest.mark.asyncio
async def test_server_mode_refuses_plaintext_writes(monkeypatch, db_session_factory):
    monkeypatch.setenv("MIMB_MODE", "server")
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    async with db_session_factory() as session:
        with pytest.raises(StatementError):
            await seed_identity(session)


@pytest.mark.asyncio
async def test_wrong_key_fails_loudly_not_garbage(monkeypatch, db_session_factory):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    async with db_session_factory() as session:
        await seed_identity(session)

    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    async with db_session_factory() as session:
        with pytest.raises((RuntimeError, StatementError)):
            await orm_access_token(session)
