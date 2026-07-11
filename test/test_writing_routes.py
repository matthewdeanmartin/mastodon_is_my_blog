from test.conftest import make_identity, make_meta_account
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from mastodon_is_my_blog import main
from mastodon_is_my_blog.queries import get_current_meta_account
from mastodon_is_my_blog.routes import writing
from mastodon_is_my_blog.store import Draft


async def async_noop(*args, **kwargs) -> None:
    return None


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch, db_session_factory) -> TestClient:
    monkeypatch.setattr(main, "init_db", async_noop)
    monkeypatch.setattr(main, "get_or_create_default_meta_account", async_noop)
    monkeypatch.setattr(main, "sync_configured_identities", async_noop)
    monkeypatch.setattr(main, "verify_all_identities", async_noop)
    monkeypatch.setattr(writing, "async_session", db_session_factory)

    def override_meta_account():
        return SimpleNamespace(id=7, username="test-meta")

    main.app.dependency_overrides[get_current_meta_account] = override_meta_account

    with TestClient(main.app) as client:
        yield client

    main.app.dependency_overrides.clear()


async def _seed_two_identities(db_session_factory) -> None:
    async with db_session_factory() as session:
        session.add(make_meta_account(meta_id=7))
        session.add(make_identity(identity_id=1, meta_account_id=7, acct="alice@example.social"))
        session.add(make_identity(identity_id=2, meta_account_id=7, acct="bob@example.social"))
        await session.commit()


@pytest.mark.asyncio
async def test_list_drafts_only_returns_own_identitys_drafts(api_client: TestClient, db_session_factory) -> None:
    await _seed_two_identities(db_session_factory)

    async with db_session_factory() as session:
        session.add(Draft(meta_account_id=7, identity_id=1, tree_json="[]"))
        session.add(Draft(meta_account_id=7, identity_id=2, tree_json="[]"))
        await session.commit()

    response = api_client.get("/api/drafts", params={"identity_id": 1})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["identity_id"] == 1


@pytest.mark.asyncio
async def test_get_draft_rejects_wrong_identity(api_client: TestClient, db_session_factory) -> None:
    await _seed_two_identities(db_session_factory)

    async with db_session_factory() as session:
        session.add(Draft(id=1, meta_account_id=7, identity_id=1, tree_json="[]"))
        await session.commit()

    own_response = api_client.get("/api/drafts/1", params={"identity_id": 1})
    other_response = api_client.get("/api/drafts/1", params={"identity_id": 2})

    assert own_response.status_code == 200
    assert other_response.status_code == 404


@pytest.mark.asyncio
async def test_delete_draft_rejects_wrong_identity(api_client: TestClient, db_session_factory) -> None:
    await _seed_two_identities(db_session_factory)

    async with db_session_factory() as session:
        session.add(Draft(id=1, meta_account_id=7, identity_id=1, tree_json="[]"))
        await session.commit()

    wrong_delete = api_client.delete("/api/drafts/1", params={"identity_id": 2})
    assert wrong_delete.status_code == 404

    right_delete = api_client.delete("/api/drafts/1", params={"identity_id": 1})
    assert right_delete.status_code == 204


@pytest.mark.asyncio
async def test_update_draft_rejects_payload_identity_mismatch(api_client: TestClient, db_session_factory) -> None:
    await _seed_two_identities(db_session_factory)

    async with db_session_factory() as session:
        session.add(Draft(id=1, meta_account_id=7, identity_id=1, tree_json="[]"))
        await session.commit()

    response = api_client.put(
        "/api/drafts/1",
        json={
            "title": None,
            "reply_to_status_id": None,
            "tree_json": "[]",
            "editor_engine": "plain",
            "language": None,
            "identity_id": 2,
        },
    )

    assert response.status_code == 404
