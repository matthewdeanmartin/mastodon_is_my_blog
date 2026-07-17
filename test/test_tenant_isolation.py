"""Two-tenant isolation: one tenant's reads must never see another's rows.

Seeds two MetaAccounts whose cached data uses IDENTICAL Mastodon-side IDs
(possible in real life: two tenants who follow the same people get the same
upstream account/post ids) and asserts the API layer keeps them apart.
"""

from datetime import datetime, UTC

import pytest
import pytest_asyncio
from fastapi import HTTPException

from mastodon_is_my_blog.routes import accounts as accounts_routes
from test.conftest import (
    make_cached_account,
    make_cached_post,
    make_identity,
    make_meta_account,
)

RECENT = datetime(2026, 6, 1, tzinfo=UTC)


@pytest.fixture
def two_tenants():
    tenant_one = make_meta_account(meta_id=1, username="tenant_1")
    tenant_two = make_meta_account(meta_id=2, username="tenant_2")
    return tenant_one, tenant_two


@pytest_asyncio.fixture
async def seeded(db_session, two_tenants, patch_async_session):
    patch_async_session(accounts_routes)
    tenant_one, tenant_two = two_tenants
    db_session.add_all([tenant_one, tenant_two])
    db_session.add_all(
        [
            make_identity(identity_id=1, meta_account_id=1, acct="one@example.social"),
            make_identity(identity_id=2, meta_account_id=2, acct="two@example.social"),
        ]
    )
    # Same upstream account id + acct, one row per tenant
    db_session.add_all(
        [
            make_cached_account(
                "shared-friend",
                meta_account_id=1,
                identity_id=1,
                acct="friend@example.social",
                last_status_at=RECENT,
            ),
            make_cached_account(
                "shared-friend",
                meta_account_id=2,
                identity_id=2,
                acct="friend@example.social",
                last_status_at=RECENT,
            ),
            # This one only tenant two follows
            make_cached_account(
                "private-friend",
                meta_account_id=2,
                identity_id=2,
                acct="secret@example.social",
                last_status_at=RECENT,
            ),
        ]
    )
    # Same upstream post id, one row per tenant
    db_session.add_all(
        [
            make_cached_post(
                "shared-post",
                meta_account_id=1,
                identity_id=1,
                author_acct="friend@example.social",
                author_id="shared-friend",
                content="<p>tenant one's copy</p>",
            ),
            make_cached_post(
                "shared-post",
                meta_account_id=2,
                identity_id=2,
                author_acct="friend@example.social",
                author_id="shared-friend",
                content="<p>tenant two's copy</p>",
            ),
        ]
    )
    await db_session.commit()
    return tenant_one, tenant_two


@pytest.mark.asyncio
async def test_blogroll_only_shows_own_tenant(seeded):
    tenant_one, tenant_two = seeded

    roll_one = await accounts_routes.get_blog_roll(identity_id=1, filter_type="all", meta=tenant_one)
    roll_two = await accounts_routes.get_blog_roll(identity_id=2, filter_type="all", meta=tenant_two)

    assert [row["acct"] for row in roll_one] == ["friend@example.social"]
    assert sorted(row["acct"] for row in roll_two) == [
        "friend@example.social",
        "secret@example.social",
    ]


@pytest.mark.asyncio
async def test_blogroll_with_other_tenants_identity_sees_nothing(seeded):
    tenant_one, tenant_two = seeded
    # Tenant one asking with tenant two's identity id: the meta filter must win.
    roll = await accounts_routes.get_blog_roll(identity_id=2, filter_type="all", meta=tenant_one)
    assert roll == []


@pytest.mark.asyncio
async def test_account_info_is_tenant_scoped(seeded):
    tenant_one, tenant_two = seeded

    # Tenant two sees its private friend; tenant one gets a 404 for it.
    info = await accounts_routes.get_account_info("secret@example.social", identity_id=2, meta=tenant_two)
    assert info["acct"] == "secret@example.social"

    with pytest.raises(HTTPException) as excinfo:
        await accounts_routes.get_account_info("secret@example.social", identity_id=1, meta=tenant_one)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_shared_post_id_resolves_to_own_tenants_copy(seeded, db_session):
    from sqlalchemy import select

    from mastodon_is_my_blog.store import CachedPost

    for meta_id, expected in ((1, "tenant one's copy"), (2, "tenant two's copy")):
        stmt = select(CachedPost).where(
            CachedPost.id == "shared-post",
            CachedPost.meta_account_id == meta_id,
        )
        rows = (await db_session.execute(stmt)).scalars().all()
        assert len(rows) == 1
        assert expected in rows[0].content
