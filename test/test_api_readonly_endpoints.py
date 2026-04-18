from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mastodon_is_my_blog import main
from mastodon_is_my_blog.link_previews import CardResponse
from mastodon_is_my_blog.queries import get_current_meta_account
from mastodon_is_my_blog.routes import accounts, admin, posts


class FakeScalars:
    def __init__(self, values: list[Any]):
        self.values = values

    def all(self) -> list[Any]:
        return self.values


class FakeResult:
    def __init__(
        self,
        *,
        scalar_value: Any = None,
        scalars_values: list[Any] | None = None,
        all_rows: list[Any] | None = None,
    ):
        self.scalar_value = scalar_value
        self.scalars_values = scalars_values or []
        self.all_rows = all_rows or []

    def scalar_one_or_none(self) -> Any:
        return self.scalar_value

    def scalar_one(self) -> Any:
        return self.scalar_value

    def scalar(self) -> Any:
        return self.scalar_value

    def scalars(self) -> FakeScalars:
        return FakeScalars(self.scalars_values)

    def all(self) -> list[Any]:
        return self.all_rows

    def one(self) -> Any:
        return self.scalar_value


class FakeSession:
    def __init__(self, results: list[FakeResult]):
        self.results = list(results)

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def execute(self, stmt) -> FakeResult:
        if not self.results:
            raise AssertionError(f"Unexpected query execution: {stmt}")
        return self.results.pop(0)


class FakeSessionFactory:
    def __init__(self, results: list[FakeResult]):
        self.results = results

    def __call__(self) -> FakeSession:
        return FakeSession(self.results)


async def async_noop(*args, **kwargs) -> None:
    return None


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "get_or_create_default_meta_account", async_noop)
    monkeypatch.setattr(main, "sync_configured_identities", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)

    def override_meta_account():
        return SimpleNamespace(id=7, username="test-meta")

    main.app.dependency_overrides[get_current_meta_account] = override_meta_account

    with TestClient(main.app) as client:
        yield client

    main.app.dependency_overrides.clear()


def test_status_endpoint_returns_up(api_client: TestClient) -> None:
    response = api_client.get("/api/status")

    assert response.status_code == 200
    assert response.json() == {"status": "up"}
    assert response.headers["x-content-type-options"] == "nosniff"


def test_spa_static_files_are_served_with_file_content_types(
    api_client: TestClient,
) -> None:
    js_name = next(main.static_dir.glob("*.js")).name
    css_name = next(main.static_dir.glob("*.css")).name

    js_response = api_client.get(f"/{js_name}")
    css_response = api_client.get(f"/{css_name}")

    assert js_response.status_code == 200
    assert js_response.headers["content-type"].startswith("application/javascript")
    assert js_response.headers["x-content-type-options"] == "nosniff"
    assert css_response.status_code == 200
    assert css_response.headers["content-type"].startswith("text/css")
    assert css_response.headers["x-content-type-options"] == "nosniff"


def test_spa_unknown_paths_fall_back_to_index_html(api_client: TestClient) -> None:
    response = api_client.get("/not-a-real-route")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_login_endpoint_redirects_to_generated_authorize_url(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class DummyClient:
        def auth_request_url(self, redirect_uris: str, scopes: list[str]) -> str:
            assert redirect_uris == "https://app.example.com/auth/callback"
            assert scopes == ["read", "write"]
            return "https://mastodon.example.com/oauth/authorize"

    async def fake_get_default_client() -> DummyClient:
        return DummyClient()

    monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
    monkeypatch.setattr(main, "get_default_client", fake_get_default_client)

    response = api_client.get("/auth/login", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == (
        "https://mastodon.example.com/oauth/authorize"
    )


def test_me_endpoint_requires_token(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_get_token() -> None:
        return None

    monkeypatch.setattr(main, "get_token", fake_get_token)

    response = api_client.get("/api/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not connected"}


def test_me_endpoint_returns_verified_account(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class DummyClient:
        def account_verify_credentials(self) -> dict[str, str]:
            return {"acct": "alice@example.com", "display_name": "Alice"}

    async def fake_get_token() -> str:
        return "token"

    async def fake_get_default_client() -> DummyClient:
        return DummyClient()

    monkeypatch.setattr(main, "get_token", fake_get_token)
    monkeypatch.setattr(main, "get_default_client", fake_get_default_client)

    response = api_client.get("/api/me")

    assert response.status_code == 200
    assert response.json()["acct"] == "alice@example.com"


def test_admin_identities_returns_serialized_identities(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    identities = [
        SimpleNamespace(id=1, acct="alice@example.com", api_base_url="https://a.example"),
        SimpleNamespace(id=2, acct="bob@example.com", api_base_url="https://b.example"),
    ]
    monkeypatch.setattr(
        admin,
        "async_session",
        FakeSessionFactory([FakeResult(scalars_values=identities)]),
    )

    response = api_client.get("/api/admin/identities")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 1, "acct": "alice@example.com", "base_url": "https://a.example"},
        {"id": 2, "acct": "bob@example.com", "base_url": "https://b.example"},
    ]


def test_admin_status_returns_connection_summary(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = SimpleNamespace(id=7, username="default")
    identity = SimpleNamespace(id=2, access_token="token")

    class DummyClient:
        def account_verify_credentials(self) -> dict[str, str]:
            return {
                "acct": "alice@example.com",
                "display_name": "Alice",
                "avatar": "https://img.example.com/alice.png",
                "note": "bio",
            }

    async def fake_get_last_sync() -> datetime:
        return datetime(2024, 1, 2, 3, 4, 5)

    monkeypatch.setattr(
        admin,
        "async_session",
        FakeSessionFactory(
            [FakeResult(scalar_value=meta), FakeResult(scalar_value=identity)]
        ),
    )
    monkeypatch.setattr(admin, "client_from_identity", lambda identity: DummyClient())
    monkeypatch.setattr(admin, "get_last_sync", fake_get_last_sync)

    response = api_client.get("/api/admin/status")

    assert response.status_code == 200
    assert response.json() == {
        "connected": True,
        "last_sync": "2024-01-02T03:04:05",
        "current_user": {
            "acct": "alice@example.com",
            "display_name": "Alice",
            "avatar": "https://img.example.com/alice.png",
            "note": "bio",
        },
    }


def test_admin_own_account_catchup_runs_full_history_sync(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = SimpleNamespace(id=5, acct="alice@example.com")
    captured: dict[str, Any] = {}

    async def fake_get_identity(meta, identity_id):
        captured["meta_id"] = meta.id
        captured["identity_id"] = identity_id
        return identity

    async def fake_sync_user_timeline_for_identity(
        meta_id: int,
        selected_identity,
        **kwargs,
    ) -> dict[str, Any]:
        captured["sync_meta_id"] = meta_id
        captured["sync_identity"] = selected_identity
        captured["kwargs"] = kwargs
        return {"status": "success", "count": 321}

    monkeypatch.setattr(admin, "_get_identity", fake_get_identity)
    monkeypatch.setattr(
        admin,
        "sync_user_timeline_for_identity",
        fake_sync_user_timeline_for_identity,
    )

    response = api_client.post("/api/admin/own-account/catchup?identity_id=5")

    assert response.status_code == 200
    assert response.json() == {"status": "success", "count": 321}
    assert captured == {
        "meta_id": 7,
        "identity_id": 5,
        "sync_meta_id": 7,
        "sync_identity": identity,
        "kwargs": {
            "force": True,
            "deep": True,
            "stop_at_cached": False,
        },
    }


def test_admin_own_account_catchup_returns_bad_gateway_on_sync_error(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_get_identity(meta, identity_id):
        return SimpleNamespace(id=5, acct="alice@example.com")

    async def fake_sync_user_timeline_for_identity(*args, **kwargs) -> dict[str, str]:
        return {"status": "error", "msg": "boom"}

    monkeypatch.setattr(admin, "_get_identity", fake_get_identity)
    monkeypatch.setattr(
        admin,
        "sync_user_timeline_for_identity",
        fake_sync_user_timeline_for_identity,
    )

    response = api_client.post("/api/admin/own-account/catchup")

    assert response.status_code == 502
    assert response.json() == {"detail": "boom"}


def test_blogroll_endpoint_returns_accounts(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = SimpleNamespace(id=5, account_id="123")
    account = SimpleNamespace(
        id="42",
        acct="friend@example.com",
        display_name="Friend",
        avatar="https://img.example.com/friend.png",
        url="https://example.com/@friend",
        note="hello",
        bot=False,
        last_status_at=datetime(2024, 1, 2, 12, 0, 0),
        cached_post_count=10,
        cached_reply_count=2,
    )
    monkeypatch.setattr(
        accounts,
        "async_session",
        FakeSessionFactory(
            [FakeResult(scalar_value=identity), FakeResult(scalars_values=[account])]
        ),
    )

    response = api_client.get("/api/accounts/blogroll?identity_id=5&filter_type=all")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "42",
            "acct": "friend@example.com",
            "display_name": "Friend",
            "avatar": "https://img.example.com/friend.png",
            "url": "https://example.com/@friend",
            "note": "hello",
            "bot": False,
            "last_status_at": "2024-01-02T12:00:00",
        }
    ]


def test_account_info_endpoint_returns_virtual_everyone(
    api_client: TestClient,
) -> None:
    response = api_client.get("/api/accounts/everyone?identity_id=5")

    assert response.status_code == 200
    assert response.json()["id"] == "everyone"
    assert response.json()["display_name"] == "Everyone"


def test_account_info_endpoint_returns_cached_account(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = SimpleNamespace(
        id="42",
        acct="friend@example.com",
        display_name="Friend",
        avatar="https://img.example.com/friend.png",
        header="https://img.example.com/header.png",
        url="https://example.com/@friend",
        note="hello",
        fields='[{"name":"site","value":"https://example.com"}]',
        bot=False,
        locked=True,
        created_at=datetime(2024, 1, 2, 12, 0, 0),
        followers_count=10,
        following_count=20,
        statuses_count=30,
        last_status_at=datetime(2024, 1, 3, 12, 0, 0),
        is_following=True,
        is_followed_by=False,
    )
    monkeypatch.setattr(
        accounts,
        "async_session",
        FakeSessionFactory(
            [
                FakeResult(scalar_value=account),
                FakeResult(scalar_value=(12, datetime(2024, 1, 9, 12, 0, 0))),
            ]
        ),
    )

    response = api_client.get("/api/accounts/friend@example.com?identity_id=5")

    assert response.status_code == 200
    assert response.json()["acct"] == "friend@example.com"
    assert response.json()["fields"] == [
        {"name": "site", "value": "https://example.com"}
    ]
    assert response.json()["cache_state"] == {
        "cached_posts": 12,
        "latest_cached_post_at": "2024-01-09T12:00:00",
        "is_stale": True,
        "stale_reason": "last_cached_post_older_than_7d",
    }


def test_account_catchup_endpoint_starts_job(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = SimpleNamespace(id=5, acct="me@example.com")
    captured: dict[str, Any] = {}

    async def fake_get_identity(meta, identity_id):
        captured["identity_id"] = identity_id
        return identity

    async def fake_start_job(meta, selected_identity, acct, mode):
        captured["meta_id"] = meta.id
        captured["acct"] = acct
        captured["mode"] = mode
        captured["identity"] = selected_identity
        return SimpleNamespace()

    monkeypatch.setattr(accounts, "_get_identity", fake_get_identity)
    monkeypatch.setattr(accounts, "start_account_catchup_job", fake_start_job)
    monkeypatch.setattr(
        accounts,
        "account_catchup_job_status",
        lambda job: {"running": True, "acct": "friend@example.com", "mode": "recent"},
    )

    response = api_client.post(
        "/api/accounts/friend@example.com/catchup?identity_id=5&mode=recent"
    )

    assert response.status_code == 200
    assert response.json() == {
        "running": True,
        "acct": "friend@example.com",
        "mode": "recent",
    }
    assert captured == {
        "identity_id": 5,
        "meta_id": 7,
        "acct": "friend@example.com",
        "mode": "recent",
        "identity": identity,
    }


def test_account_catchup_status_endpoint_returns_existing_job(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_get_identity(meta, identity_id):
        return SimpleNamespace(id=identity_id, acct="me@example.com")

    monkeypatch.setattr(accounts, "_get_identity", fake_get_identity)
    monkeypatch.setattr(
        accounts,
        "get_account_catchup_job",
        lambda meta_id, identity_id, acct: SimpleNamespace(
            meta_id=meta_id, identity_id=identity_id, acct=acct
        ),
    )
    monkeypatch.setattr(
        accounts,
        "account_catchup_job_status",
        lambda job: {"running": False, "acct": job.acct, "mode": "deep"},
    )

    response = api_client.get("/api/accounts/friend@example.com/catchup/status?identity_id=5")

    assert response.status_code == 200
    assert response.json() == {
        "running": False,
        "acct": "friend@example.com",
        "mode": "deep",
    }


def test_account_catchup_cancel_endpoint_cancels_running_job(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_get_identity(meta, identity_id):
        return SimpleNamespace(id=identity_id, acct="me@example.com")

    monkeypatch.setattr(accounts, "_get_identity", fake_get_identity)
    monkeypatch.setattr(
        accounts,
        "cancel_account_catchup_job",
        lambda meta_id, identity_id, acct: meta_id == 7
        and identity_id == 5
        and acct == "friend@example.com",
    )

    response = api_client.delete("/api/accounts/friend@example.com/catchup?identity_id=5")

    assert response.status_code == 200
    assert response.json() == {"cancelled": True}


def test_seen_endpoint_returns_seen_post_ids(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_get_seen_posts(meta_id: int, post_ids: list[str]) -> set[str]:
        assert meta_id == 7
        assert post_ids == ["1", "2", "3"]
        return {"1", "3"}

    monkeypatch.setattr(posts, "get_seen_posts", fake_get_seen_posts)

    response = api_client.get("/api/posts/seen?ids=1,2,3")

    assert response.status_code == 200
    assert set(response.json()["seen"]) == {"1", "3"}


def test_unread_count_endpoint_returns_remaining_count(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_get_unread_count(meta_id: int) -> int:
        assert meta_id == 7
        return 2

    monkeypatch.setattr(
        posts,
        "async_session",
        FakeSessionFactory([FakeResult(scalar_value=7)]),
    )
    monkeypatch.setattr(posts, "get_unread_count", fake_get_unread_count)

    response = api_client.get("/api/posts/unread-count?identity_id=5")

    assert response.status_code == 200
    assert response.json() == {"unread_count": 5}


def test_public_posts_endpoint_returns_serialized_posts(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    post = SimpleNamespace(
        id="p1",
        content="<p>Hello</p>",
        author_acct="alice@example.com",
        created_at=datetime(2024, 1, 2, 12, 0, 0),
        media_attachments='[{"type":"image"}]',
        replies_count=1,
        reblogs_count=2,
        favourites_count=3,
        is_reblog=False,
        is_reply=False,
        has_link=True,
        tags='["Intro"]',
    )
    account_row = SimpleNamespace(acct="alice@example.com", avatar="https://img.example.com/alice.png", display_name="Alice")

    monkeypatch.setattr(
        posts,
        "async_session",
        FakeSessionFactory([
            FakeResult(all_rows=[(post, "p1")]),
            FakeResult(all_rows=[account_row]),
        ]),
    )

    response = api_client.get("/api/posts?identity_id=5&filter_type=all")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": "p1",
                "content": "<p>Hello</p>",
                "author_acct": "alice@example.com",
                "author_avatar": "https://img.example.com/alice.png",
                "author_display_name": "Alice",
                "created_at": "2024-01-02T12:00:00",
                "is_read": True,
                "media_attachments": [{"type": "image"}],
                "counts": {"replies": 1, "reblogs": 2, "likes": 3},
                "is_reblog": False,
                "is_reply": False,
                "has_link": True,
                "tags": ["Intro"],
            }
        ],
        "next_cursor": None,
    }


def test_shorts_endpoint_uses_shorts_filter(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_get_public_posts(
        *,
        identity_id: int,
        user: str | None,
        filter_type: str,
        limit: int,
        before: str | None,
        meta: Any,
    ) -> dict[str, Any]:
        captured["identity_id"] = identity_id
        captured["user"] = user
        captured["filter_type"] = filter_type
        captured["limit"] = limit
        captured["before"] = before
        captured["meta_id"] = meta.id
        return {"items": [{"id": "short-1"}], "next_cursor": None}

    monkeypatch.setattr(posts, "get_public_posts", fake_get_public_posts)

    response = api_client.get("/api/posts/shorts?identity_id=5&user=alice")

    assert response.status_code == 200
    assert response.json() == {"items": [{"id": "short-1"}], "next_cursor": None}
    assert captured == {
        "identity_id": 5,
        "user": "alice",
        "filter_type": "shorts",
        "limit": 30,
        "before": None,
        "meta_id": 7,
    }


def test_storms_endpoint_returns_root_and_branch_posts(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = SimpleNamespace(
        id="root-1",
        content="storm root",
        created_at=datetime(2024, 1, 2, 12, 0, 0),
        media_attachments=None,
        replies_count=5,
        favourites_count=6,
        author_acct="alice@example.com",
        author_id="author-1",
    )
    reply = SimpleNamespace(
        id="reply-1",
        content="storm reply",
        created_at=datetime(2024, 1, 2, 12, 5, 0),
        media_attachments=None,
        replies_count=0,
        favourites_count=1,
        author_id="author-1",
        in_reply_to_id="root-1",
    )

    async def fake_get_seen_posts(meta_id: int, post_ids: list[str]) -> set[str]:
        assert meta_id == 7
        assert post_ids == ["root-1", "reply-1"]
        return {"reply-1"}

    account_row = SimpleNamespace(acct="alice@example.com", avatar="https://img.example.com/alice.png", display_name="Alice")

    monkeypatch.setattr(
        posts,
        "async_session",
        FakeSessionFactory(
            [
                FakeResult(scalars_values=[root]),
                FakeResult(scalars_values=[reply]),
                FakeResult(all_rows=[account_row]),
            ]
        ),
    )
    monkeypatch.setattr(posts, "get_seen_posts", fake_get_seen_posts)

    response = api_client.get("/api/posts/storms?identity_id=5")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "root": {
                    "id": "root-1",
                    "content": "storm root",
                    "created_at": "2024-01-02T12:00:00",
                    "media": [],
                    "counts": {"replies": 5, "likes": 6},
                    "author_acct": "alice@example.com",
                    "author_avatar": "https://img.example.com/alice.png",
                    "author_display_name": "Alice",
                    "is_read": False,
                },
                "branches": [
                    {
                        "id": "reply-1",
                        "content": "storm reply",
                        "media": [],
                        "counts": {"replies": 0, "likes": 1},
                        "is_read": True,
                        "children": [],
                    }
                ],
            }
        ],
        "next_cursor": None,
    }


def test_hashtags_endpoint_aggregates_and_sorts_tags(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_hashtag_counts(meta_id, identity_id, user=None):
        captured["meta_id"] = meta_id
        captured["identity_id"] = identity_id
        captured["user"] = user
        return [
            {"name": "tag", "count": 2},
            {"name": "other", "count": 1},
        ]

    from mastodon_is_my_blog import duck
    monkeypatch.setattr(duck, "hashtag_counts", fake_hashtag_counts)

    response = api_client.get("/api/posts/hashtags?identity_id=5")

    assert response.status_code == 200
    assert response.json() == [
        {"name": "tag", "count": 2},
        {"name": "other", "count": 1},
    ]
    assert captured["identity_id"] == 5
    assert captured["user"] is None


def test_counts_endpoint_returns_sidebar_counts(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_get_counts_optimized(
        session: Any, meta_id: int, identity_id: int, user: str | None
    ) -> dict[str, int]:
        captured["meta_id"] = meta_id
        captured["identity_id"] = identity_id
        captured["user"] = user
        return {"all": 10, "links": 3}

    monkeypatch.setattr(posts, "async_session", FakeSessionFactory([]))
    monkeypatch.setattr(posts, "get_counts_optimized", fake_get_counts_optimized)

    response = api_client.get("/api/posts/counts?identity_id=5&user=everyone")

    assert response.status_code == 200
    assert response.json() == {"all": 10, "links": 3}
    assert captured == {"meta_id": 7, "identity_id": 5, "user": None}


def test_card_endpoint_returns_card_payload(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch_card(url: str) -> CardResponse:
        assert url == "https://example.com/post"
        return CardResponse(
            url="https://example.com/final",
            title="Example",
            description="Desc",
            site_name="Site",
            image="https://example.com/card.png",
            favicon="https://example.com/favicon.ico",
        )

    monkeypatch.setattr(posts, "fetch_card", fake_fetch_card)

    response = api_client.get("/api/posts/card?url=https://example.com/post")

    assert response.status_code == 200
    assert response.json()["title"] == "Example"
    assert response.json()["url"] == "https://example.com/final"


def test_post_context_endpoint_returns_thread_context(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class DummyClient:
        def status_context(self, post_id: str) -> dict[str, list[dict[str, str]]]:
            assert post_id == "abc123"
            return {"ancestors": [{"id": "p0"}], "descendants": [{"id": "p2"}]}

        def status(self, post_id: str) -> dict[str, str]:
            assert post_id == "abc123"
            return {"id": "abc123"}

    async def fake_client_from_identity_id(identity_id: int) -> DummyClient:
        assert identity_id == 5
        return DummyClient()

    monkeypatch.setattr(posts, "client_from_identity_id", fake_client_from_identity_id)

    response = api_client.get("/api/posts/abc123/context?identity_id=5")

    assert response.status_code == 200
    assert response.json() == {
        "ancestors": [{"id": "p0"}],
        "target": {"id": "abc123"},
        "descendants": [{"id": "p2"}],
    }


def test_single_post_endpoint_returns_cached_post(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    post = SimpleNamespace(
        id="p1",
        content="<p>Hello</p>",
        author_acct="alice@example.com",
        created_at=datetime(2024, 1, 2, 12, 0, 0),
        media_attachments='[{"type":"image"}]',
        replies_count=1,
        reblogs_count=2,
        favourites_count=3,
        is_reblog=False,
        is_reply=True,
    )
    monkeypatch.setattr(
        posts,
        "async_session",
        FakeSessionFactory([FakeResult(scalar_value=post)]),
    )

    response = api_client.get("/api/posts/p1")

    assert response.status_code == 200
    assert response.json() == {
        "id": "p1",
        "content": "<p>Hello</p>",
        "author_acct": "alice@example.com",
        "created_at": "2024-01-02T12:00:00",
        "media_attachments": [{"type": "image"}],
        "counts": {"replies": 1, "reblogs": 2, "likes": 3},
        "is_reblog": False,
        "is_reply": True,
    }
