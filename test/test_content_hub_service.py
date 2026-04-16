from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from mastodon_is_my_blog import content_hub_matching, content_hub_service
from mastodon_is_my_blog.datetime_helpers import utc_now
from mastodon_is_my_blog.store import ContentHubGroup, ContentHubGroupTerm
from test.conftest import make_identity, make_meta_account


def make_group(
    group_id: int = 1,
    *,
    meta_account_id: int = 1,
    identity_id: int = 1,
    name: str = "Python",
    slug: str = "python",
    source_type: str = "client_bundle",
    is_read_only: bool = False,
    last_fetched_at: datetime | None = None,
) -> ContentHubGroup:
    now = datetime(2024, 1, 1)
    return ContentHubGroup(
        id=group_id,
        meta_account_id=meta_account_id,
        identity_id=identity_id,
        name=name,
        slug=slug,
        source_type=source_type,
        is_read_only=is_read_only,
        last_fetched_at=last_fetched_at,
        created_at=now,
        updated_at=now,
    )


def make_term(
    term_id: int = 1,
    *,
    group_id: int = 1,
    term: str = "python",
    term_type: str = "hashtag",
    normalized_term: str = "python",
) -> ContentHubGroupTerm:
    return ContentHubGroupTerm(
        id=term_id,
        group_id=group_id,
        term=term,
        term_type=term_type,
        normalized_term=normalized_term,
        created_at=datetime(2024, 1, 1),
    )


def test_make_slug_normalizes_names() -> None:
    assert content_hub_service.make_slug("  Python & AI_News  ") == "python-ai-news"


@pytest.mark.asyncio
async def test_is_group_stale_handles_missing_recent_and_old_timestamps() -> None:
    assert await content_hub_service.is_group_stale(make_group(last_fetched_at=None)) is True
    assert (
        await content_hub_service.is_group_stale(
            make_group(last_fetched_at=utc_now())
        )
        is False
    )
    assert (
        await content_hub_service.is_group_stale(
            make_group(
                last_fetched_at=utc_now()
                - timedelta(hours=content_hub_service.STALE_AFTER_HOURS + 1)
            )
        )
        is True
    )


@pytest.mark.asyncio
async def test_sync_server_follow_groups_creates_and_removes_groups(
    db_session,
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(content_hub_service)
    identity = make_identity()
    obsolete_group = make_group(
        group_id=100,
        name="#OldTag",
        slug="oldtag",
        source_type="server_follow",
        is_read_only=True,
    )
    db_session.add_all([make_meta_account(), identity, obsolete_group])
    await db_session.commit()

    client = MagicMock()
    client.followed_tags.return_value = [{"name": "Python"}, {"name": "Fediverse Jobs"}]

    with patch.object(content_hub_service, "client_from_identity", return_value=client):
        result = await content_hub_service.sync_server_follow_groups(1, identity)

    async with db_session_factory() as session:
        groups = (
            await session.execute(
                select(ContentHubGroup).order_by(ContentHubGroup.slug)
            )
        ).scalars().all()
        terms = (
            await session.execute(
                select(ContentHubGroupTerm).order_by(ContentHubGroupTerm.normalized_term)
            )
        ).scalars().all()

    assert result == {"created": 2, "removed": 1}
    assert [(group.name, group.slug, group.is_read_only) for group in groups] == [
        ("#Fediverse Jobs", "fediverse-jobs", True),
        ("#Python", "python", True),
    ]
    assert [(term.term, term.normalized_term) for term in terms] == [
        ("Fediverse Jobs", "fediverse jobs"),
        ("Python", "python"),
    ]


@pytest.mark.asyncio
async def test_sync_server_follow_groups_returns_zeroes_when_client_fails() -> None:
    identity = make_identity()
    client = MagicMock()
    client.followed_tags.side_effect = RuntimeError("boom")

    with patch.object(content_hub_service, "client_from_identity", return_value=client):
        result = await content_hub_service.sync_server_follow_groups(1, identity)

    assert result == {"created": 0, "removed": 0}


@pytest.mark.asyncio
async def test_refresh_group_raises_for_missing_group(patch_async_session) -> None:
    patch_async_session(content_hub_service)
    with pytest.raises(ValueError, match="ContentHubGroup 999 not found"):
        await content_hub_service.refresh_group(1, make_identity(), 999)


@pytest.mark.asyncio
async def test_refresh_group_skips_fresh_groups(db_session, patch_async_session) -> None:
    patch_async_session(content_hub_service)
    db_session.add_all(
        [
            make_meta_account(),
            make_identity(),
            make_group(last_fetched_at=utc_now()),
        ]
    )
    await db_session.commit()

    result = await content_hub_service.refresh_group(1, make_identity(), 1)

    assert result == {"fetched": 0, "matched": 0}


@pytest.mark.asyncio
async def test_refresh_group_fetches_terms_records_matches_and_updates_timestamp(
    db_session,
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(content_hub_service)
    identity = make_identity()
    group = make_group(
        last_fetched_at=utc_now()
        - timedelta(hours=content_hub_service.STALE_AFTER_HOURS + 1)
    )
    hashtag_term = make_term(term_id=1, term="#Python", normalized_term="python")
    search_term = make_term(
        term_id=2,
        term="python jobs",
        term_type="search",
        normalized_term="python jobs",
    )
    db_session.add_all([make_meta_account(), identity, group, hashtag_term, search_term])
    await db_session.commit()

    client = MagicMock()
    client.timeline_hashtag.return_value = [{"id": "hash-1"}, {"id": "hash-2"}]
    client.search.return_value = {"statuses": [{"id": "search-1"}]}
    bulk_upsert_mock = AsyncMock(return_value=(2, 0))
    hashtag_match_mock = AsyncMock(return_value=2)
    search_match_mock = AsyncMock(return_value=1)

    with (
        patch.object(content_hub_service, "client_from_identity", return_value=client),
        patch.object(content_hub_service, "bulk_upsert_posts", bulk_upsert_mock),
        patch.object(content_hub_service, "record_search_matches", search_match_mock),
        patch.object(content_hub_matching, "retro_match_hashtag_term", hashtag_match_mock),
    ):
        result = await content_hub_service.refresh_group(1, identity, group.id)

    async with db_session_factory() as session:
        refreshed_group = await session.get(ContentHubGroup, group.id)

    assert result == {"fetched": 3, "matched": 3}
    assert refreshed_group is not None
    assert refreshed_group.last_fetched_at is not None
    assert client.timeline_hashtag.call_args.args == ("python",)
    assert client.timeline_hashtag.call_args.kwargs == {"limit": 40}
    assert client.search.call_args.args == ("python jobs",)
    assert client.search.call_args.kwargs == {"result_type": "statuses", "limit": 40}
    assert bulk_upsert_mock.await_args_list[0].kwargs == {
        "discovery_source": "hashtag",
        "content_hub_only": True,
    }
    assert bulk_upsert_mock.await_args_list[1].kwargs == {
        "discovery_source": "search",
        "content_hub_only": True,
    }
    assert hashtag_match_mock.await_args.args[1:4] == (1, 1, group.id)
    assert hashtag_match_mock.await_args.args[4].id == hashtag_term.id
    assert hashtag_match_mock.await_args.args[4].normalized_term == "python"
    assert search_match_mock.await_args.args[1:4] == (1, 1, group.id)
    assert search_match_mock.await_args.args[4].id == search_term.id
    assert search_match_mock.await_args.args[4].term == "python jobs"
    assert search_match_mock.await_args.args[5] == ["search-1"]


@pytest.mark.asyncio
async def test_refresh_group_continues_after_term_errors(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(content_hub_service)
    identity = make_identity()
    group = make_group(
        last_fetched_at=utc_now()
        - timedelta(hours=content_hub_service.STALE_AFTER_HOURS + 1)
    )
    hashtag_term = make_term(term_id=1, term="#Python", normalized_term="python")
    search_term = make_term(
        term_id=2,
        term="python jobs",
        term_type="search",
        normalized_term="python jobs",
    )
    db_session.add_all([make_meta_account(), identity, group, hashtag_term, search_term])
    await db_session.commit()

    client = MagicMock()
    client.timeline_hashtag.side_effect = RuntimeError("boom")
    client.search.return_value = {"statuses": []}

    with patch.object(content_hub_service, "client_from_identity", return_value=client):
        result = await content_hub_service.refresh_group(1, identity, group.id, force=True)

    assert result == {"fetched": 0, "matched": 0}


@pytest.mark.asyncio
async def test_create_client_bundle_persists_group_and_normalized_terms(
    db_session,
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(content_hub_service)
    db_session.add_all([make_meta_account(), make_identity()])
    await db_session.commit()

    retro_match_mock = AsyncMock(return_value=2)
    with patch.object(
        content_hub_service, "retro_match_new_bundle", retro_match_mock
    ):
        group = await content_hub_service.create_client_bundle(
            1,
            1,
            "Python & Jobs",
            [
                {"term": " #Python ", "term_type": "hashtag"},
                {"term": " From:me ", "term_type": "search"},
            ],
        )

    async with db_session_factory() as session:
        stored_group = await session.get(ContentHubGroup, group.id)
        terms = (
            await session.execute(
                select(ContentHubGroupTerm)
                .where(ContentHubGroupTerm.group_id == group.id)
                .order_by(ContentHubGroupTerm.id)
            )
        ).scalars().all()

    assert stored_group is not None
    assert stored_group.slug == "python-jobs"
    assert [(term.term, term.term_type, term.normalized_term) for term in terms] == [
        (" #Python ", "hashtag", "#python"),
        (" From:me ", "search", "from:me"),
    ]
    assert retro_match_mock.await_count == 1


@pytest.mark.asyncio
async def test_update_client_bundle_replaces_terms_and_updates_slug(
    db_session,
    db_session_factory,
    patch_async_session,
) -> None:
    patch_async_session(content_hub_service)
    group = make_group(name="Old Bundle", slug="old-bundle")
    old_term = make_term(term_id=1, term="#old", normalized_term="old")
    db_session.add_all([make_meta_account(), make_identity(), group, old_term])
    await db_session.commit()

    retro_match_mock = AsyncMock(return_value=1)
    with patch.object(
        content_hub_service, "retro_match_new_bundle", retro_match_mock
    ):
        updated_group = await content_hub_service.update_client_bundle(
            1,
            1,
            group.id,
            "New Bundle",
            [
                {"term": "#Python", "term_type": "hashtag"},
                {"term": "has:media", "term_type": "search"},
            ],
        )

    async with db_session_factory() as session:
        stored_group = await session.get(ContentHubGroup, updated_group.id)
        terms = (
            await session.execute(
                select(ContentHubGroupTerm)
                .where(ContentHubGroupTerm.group_id == updated_group.id)
                .order_by(ContentHubGroupTerm.id)
            )
        ).scalars().all()

    assert stored_group is not None
    assert stored_group.name == "New Bundle"
    assert stored_group.slug == "new-bundle"
    assert [(term.term, term.normalized_term) for term in terms] == [
        ("#Python", "python"),
        ("has:media", "has:media"),
    ]
    assert retro_match_mock.await_count == 1


@pytest.mark.asyncio
async def test_update_client_bundle_rejects_read_only_groups(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(content_hub_service)
    db_session.add_all(
        [
            make_meta_account(),
            make_identity(),
            make_group(source_type="server_follow", is_read_only=True),
        ]
    )
    await db_session.commit()

    with pytest.raises(ValueError, match="Cannot edit a read-only server-follow group"):
        await content_hub_service.update_client_bundle(1, 1, 1, "Name", [])
