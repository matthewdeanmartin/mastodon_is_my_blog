from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from mastodon_is_my_blog import main
from mastodon_is_my_blog.queries import get_current_meta_account
from mastodon_is_my_blog.routes import content_hub
from mastodon_is_my_blog.store import (
    CachedAccount,
    ContentHubGroup,
    ContentHubGroupTerm,
    ContentHubPostMatch,
)
from test.conftest import make_cached_post, make_identity, make_meta_account


async def async_noop(*args, **kwargs) -> None:
    return None


def make_group(
    group_id: int = 1,
    *,
    meta_account_id: int = 7,
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


@pytest.fixture
def api_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session_factory,
) -> TestClient:
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "get_or_create_default_meta_account", async_noop)
    monkeypatch.setattr(main, "bootstrap_identities_from_env", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)
    monkeypatch.setattr(content_hub, "async_session", db_session_factory)

    def override_meta_account():
        return SimpleNamespace(id=7, username="test-meta")

    main.app.dependency_overrides[get_current_meta_account] = override_meta_account

    with TestClient(main.app) as client:
        yield client

    main.app.dependency_overrides.clear()


def test_encode_and_decode_cursor_round_trip() -> None:
    created_at = datetime(2024, 1, 2, 3, 4, 5)
    encoded = content_hub.encode_cursor(created_at, "post-1")

    assert content_hub.decode_cursor(encoded) == (created_at, "post-1")


def test_decode_cursor_rejects_invalid_input() -> None:
    with pytest.raises(HTTPException, match="400: Invalid cursor"):
        content_hub.decode_cursor("not-base64")


@pytest.mark.asyncio
async def test_resolve_identity_returns_matching_identity(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(content_hub)
    identity = make_identity(identity_id=5, meta_account_id=7)
    db_session.add_all([make_meta_account(meta_id=7), identity])
    await db_session.commit()

    resolved = await content_hub.resolve_identity(7, 5)

    assert resolved.id == identity.id


@pytest.mark.asyncio
async def test_resolve_identity_raises_not_found(
    db_session,
    patch_async_session,
) -> None:
    patch_async_session(content_hub)
    db_session.add(make_meta_account(meta_id=7))
    await db_session.commit()

    with pytest.raises(HTTPException, match="404: Identity not found"):
        await content_hub.resolve_identity(7, 999)


def test_list_groups_returns_groups_and_terms(
    api_client: TestClient,
    db_session_factory,
) -> None:
    async def seed_data() -> None:
        async with db_session_factory() as session:
            session.add_all(
                [
                    make_meta_account(meta_id=7),
                    make_identity(identity_id=1, meta_account_id=7),
                    make_group(
                        group_id=1,
                        name="Zeta Follow",
                        slug="zeta-follow",
                        source_type="server_follow",
                        is_read_only=True,
                    ),
                    make_group(
                        group_id=2,
                        name="Alpha Bundle",
                        slug="alpha-bundle",
                        source_type="client_bundle",
                    ),
                    make_term(term_id=1, group_id=1, term="zeta", normalized_term="zeta"),
                    make_term(term_id=2, group_id=2, term="#alpha", normalized_term="alpha"),
                ]
            )
            await session.commit()

    import anyio

    anyio.run(seed_data)

    response = api_client.get("/api/content-hub/groups?identity_id=1")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 2,
            "name": "Alpha Bundle",
            "slug": "alpha-bundle",
            "source_type": "client_bundle",
            "is_read_only": False,
            "last_fetched_at": None,
            "terms": [{"id": 2, "term": "#alpha", "term_type": "hashtag"}],
        },
        {
            "id": 1,
            "name": "Zeta Follow",
            "slug": "zeta-follow",
            "source_type": "server_follow",
            "is_read_only": True,
            "last_fetched_at": None,
            "terms": [{"id": 1, "term": "zeta", "term_type": "hashtag"}],
        },
    ]


def test_get_group_posts_filters_jobs_and_builds_cursor(
    api_client: TestClient,
    db_session_factory,
) -> None:
    async def seed_data() -> None:
        async with db_session_factory() as session:
            job_one = make_cached_post(
                post_id="job-2",
                meta_account_id=7,
                identity_id=1,
                author_acct="alice@example.social",
                content="<p>We are hiring</p>",
                has_video=True,
            )
            job_one.tags = '["jobs"]'
            job_one.media_attachments = '[{"type":"video"}]'
            job_one.created_at = datetime(2024, 1, 3, 12, 0, 0)

            job_two = make_cached_post(
                post_id="job-1",
                meta_account_id=7,
                identity_id=1,
                author_acct="bob@example.social",
                content="<p>Remote job opening</p>",
            )
            job_two.tags = '["python"]'
            job_two.created_at = datetime(2024, 1, 2, 12, 0, 0)

            regular_post = make_cached_post(
                post_id="note-1",
                meta_account_id=7,
                identity_id=1,
                author_acct="carol@example.social",
                content="<p>Shipping a release</p>",
            )
            regular_post.tags = '["release"]'
            regular_post.created_at = datetime(2024, 1, 1, 12, 0, 0)

            session.add_all(
                [
                    make_meta_account(meta_id=7),
                    make_identity(identity_id=1, meta_account_id=7),
                    make_group(
                        group_id=1,
                        last_fetched_at=datetime.utcnow() - timedelta(minutes=10),
                    ),
                    make_term(term_id=1, group_id=1, term="#python"),
                    job_one,
                    job_two,
                    regular_post,
                    CachedAccount(
                        id="acct-1",
                        meta_account_id=7,
                        mastodon_identity_id=1,
                        acct="alice@example.social",
                        display_name="Alice",
                        avatar="https://example.social/alice.png",
                        url="https://example.social/@alice",
                        note="",
                        bot=False,
                        locked=False,
                        created_at=None,
                        header="https://example.social/header.png",
                        fields="[]",
                        followers_count=1,
                        following_count=1,
                        statuses_count=1,
                        is_following=False,
                        is_followed_by=False,
                        last_status_at=None,
                        cached_post_count=0,
                        cached_reply_count=0,
                    ),
                    CachedAccount(
                        id="acct-2",
                        meta_account_id=7,
                        mastodon_identity_id=1,
                        acct="bob@example.social",
                        display_name="Bob",
                        avatar="https://example.social/bob.png",
                        url="https://example.social/@bob",
                        note="",
                        bot=False,
                        locked=False,
                        created_at=None,
                        header="https://example.social/header.png",
                        fields="[]",
                        followers_count=1,
                        following_count=1,
                        statuses_count=1,
                        is_following=False,
                        is_followed_by=False,
                        last_status_at=None,
                        cached_post_count=0,
                        cached_reply_count=0,
                    ),
                    ContentHubPostMatch(
                        group_id=1,
                        post_id="job-2",
                        meta_account_id=7,
                        fetched_by_identity_id=1,
                        matched_term_id=1,
                        matched_via="hashtag",
                        created_at=datetime(2024, 1, 3),
                    ),
                    ContentHubPostMatch(
                        group_id=1,
                        post_id="job-1",
                        meta_account_id=7,
                        fetched_by_identity_id=1,
                        matched_term_id=1,
                        matched_via="hashtag",
                        created_at=datetime(2024, 1, 2),
                    ),
                    ContentHubPostMatch(
                        group_id=1,
                        post_id="note-1",
                        meta_account_id=7,
                        fetched_by_identity_id=1,
                        matched_term_id=1,
                        matched_via="hashtag",
                        created_at=datetime(2024, 1, 1),
                    ),
                ]
            )
            await session.commit()

    import anyio

    anyio.run(seed_data)

    response = api_client.get(
        "/api/content-hub/groups/1/posts?identity_id=1&tab=jobs&limit=1"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stale"] is False
    assert payload["group"]["id"] == 1
    assert payload["next_cursor"] is not None
    assert payload["items"] == [
        {
            "id": "job-2",
            "content": "<p>We are hiring</p>",
            "author_acct": "alice@example.social",
            "author_avatar": "https://example.social/alice.png",
            "author_display_name": "Alice",
            "created_at": "2024-01-03T12:00:00",
            "media_attachments": [{"type": "video"}],
            "tags": ["jobs"],
            "counts": {"replies": 0, "reblogs": 0, "likes": 0},
            "has_video": True,
            "has_link": False,
            "is_reblog": False,
            "is_reply": False,
        }
    ]


def test_get_group_posts_rejects_invalid_cursor(
    api_client: TestClient,
    db_session_factory,
) -> None:
    async def seed_data() -> None:
        async with db_session_factory() as session:
            session.add_all(
                [
                    make_meta_account(meta_id=7),
                    make_identity(identity_id=1, meta_account_id=7),
                    make_group(group_id=1),
                ]
            )
            await session.commit()

    import anyio

    anyio.run(seed_data)

    response = api_client.get(
        "/api/content-hub/groups/1/posts?identity_id=1&before=not-a-cursor"
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid cursor"}


def test_force_refresh_group_calls_service(
    api_client: TestClient,
    db_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def seed_data() -> None:
        async with db_session_factory() as session:
            session.add_all(
                [
                    make_meta_account(meta_id=7),
                    make_identity(identity_id=1, meta_account_id=7),
                    make_group(group_id=1),
                ]
            )
            await session.commit()

    import anyio

    anyio.run(seed_data)

    refresh_mock = AsyncMock(return_value={"fetched": 3, "matched": 2})
    monkeypatch.setattr(content_hub, "refresh_group", refresh_mock)

    response = api_client.post("/api/content-hub/groups/1/refresh?identity_id=1")

    assert response.status_code == 200
    assert response.json() == {"refreshed": True, "fetched": 3, "matched": 2}
    assert refresh_mock.await_args.args[:3] == (7, ANY, 1)
    assert refresh_mock.await_args.kwargs == {"force": True}


def test_sync_follows_calls_service(
    api_client: TestClient,
    db_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def seed_data() -> None:
        async with db_session_factory() as session:
            session.add_all(
                [
                    make_meta_account(meta_id=7),
                    make_identity(identity_id=1, meta_account_id=7),
                ]
            )
            await session.commit()

    import anyio

    anyio.run(seed_data)

    sync_mock = AsyncMock(return_value={"created": 2, "removed": 1})
    monkeypatch.setattr(content_hub, "sync_server_follow_groups", sync_mock)

    response = api_client.post("/api/content-hub/sync-follows?identity_id=1")

    assert response.status_code == 200
    assert response.json() == {"created": 2, "removed": 1}
    assert sync_mock.await_args.args[:2] == (7, ANY)
