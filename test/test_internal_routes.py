"""Control-plane hand-off API tests (spec/paid_hosting/control_plane_handoff.md §6).

Covers: bearer auth, local-mode absence, provision/purge idempotency,
two-tenant isolation of export and purge, usage, and the "export is
self-host bootable" acceptance test.

Uses httpx.AsyncClient over ASGITransport (not TestClient) so the routes and
the aiosqlite test database share one event loop.
"""

import sqlite3
import zipfile
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mastodon_is_my_blog import storm_export, tenant_export
from mastodon_is_my_blog.routes import internal
from mastodon_is_my_blog.store import (
    CachedPost,
    MastodonIdentity,
    MetaAccount,
)
from test.conftest import (
    make_cached_account,
    make_cached_post,
    make_identity,
    make_meta_account,
)

SECRET = "test-handoff-secret"
AUTH = {"Authorization": f"Bearer {SECRET}"}


@pytest_asyncio.fixture
async def client(monkeypatch, patch_async_session, tmp_path):
    monkeypatch.setenv("HANDOFF_SHARED_SECRET", SECRET)
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
    patch_async_session(tenant_export, storm_export)
    app = FastAPI()
    app.include_router(internal.router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://internal.test"
    ) as http:
        yield http


@pytest.fixture(autouse=True)
def reset_sync_debounce():
    """The sync→rebuild debounce set is module-global; clear it around every
    test so a background task that hasn't drained can't leak 'already_running'
    into the next test (tenant 1 is reused across the module)."""
    internal.syncing_tenants.clear()
    yield
    internal.syncing_tenants.clear()


@pytest_asyncio.fixture
async def two_tenants_seeded(db_session):
    """MetaAccounts tenant_1 / tenant_2 with distinct identities and posts.

    Tenant 1's posts form a storm (root + self-reply) so the blog export has
    something to render; both tenants share an upstream post id to prove the
    export filter is on meta_account_id, not post id.
    """
    db_session.add_all(
        [
            make_meta_account(meta_id=1, username="tenant_1"),
            make_meta_account(meta_id=2, username="tenant_2"),
        ]
    )
    db_session.add_all(
        [
            make_identity(
                identity_id=1,
                meta_account_id=1,
                acct="one@example.social",
                account_id="1001",
                access_token="secret-token-one",
                client_secret="secret-client-one",
            ),
            make_identity(
                identity_id=2,
                meta_account_id=2,
                acct="two@example.social",
                account_id="2002",
                access_token="secret-token-two",
                client_secret="secret-client-two",
            ),
        ]
    )
    root = make_cached_post(
        "storm-root",
        meta_account_id=1,
        identity_id=1,
        author_acct="one@example.social",
        author_id="1001",
        content="<p>tenant one storm root</p>",
    )
    reply = make_cached_post(
        "storm-reply",
        meta_account_id=1,
        identity_id=1,
        author_acct="one@example.social",
        author_id="1001",
        content="<p>tenant one storm reply</p>",
        is_reply=True,
        in_reply_to_id="storm-root",
        in_reply_to_account_id="1001",
    )
    reply.created_at = datetime(2024, 1, 2)
    db_session.add_all(
        [
            root,
            reply,
            make_cached_post(
                "shared-post-id",
                meta_account_id=1,
                identity_id=1,
                author_acct="one@example.social",
                author_id="1001",
                content="<p>tenant one copy</p>",
            ),
            make_cached_post(
                "shared-post-id",
                meta_account_id=2,
                identity_id=2,
                author_acct="two@example.social",
                author_id="2002",
                content="<p>TENANT TWO SECRET CONTENT</p>",
            ),
        ]
    )
    db_session.add_all(
        [
            make_cached_account(
                "friend-1", meta_account_id=1, identity_id=1, acct="f1@example.social"
            ),
            make_cached_account(
                "friend-2", meta_account_id=2, identity_id=2, acct="f2@example.social"
            ),
        ]
    )
    await db_session.commit()


# --- Auth (§6 item 2) ---


@pytest.mark.asyncio
async def test_all_routes_403_without_secret(client):
    requests = [
        ("GET", "/internal/health", None),
        ("GET", "/internal/tenants/1/usage", None),
        ("POST", "/internal/tenants/1/provision", {"job_id": 1}),
        ("POST", "/internal/tenants/1/sync", {"job_id": 1}),
        ("PUT", "/internal/tenants/1/limits", {"job_id": 1}),
        ("POST", "/internal/tenants/1/rebuild-blog", {"job_id": 1}),
        ("POST", "/internal/tenants/1/export", {"job_id": 1}),
        ("DELETE", "/internal/tenants/1", {"job_id": 1}),
    ]
    for method, path, body in requests:
        no_header = await client.request(method, path, json=body)
        assert no_header.status_code == 403, path
        wrong = await client.request(
            method, path, json=body, headers={"Authorization": "Bearer wrong"}
        )
        assert wrong.status_code == 403, path


@pytest.mark.asyncio
async def test_403_when_secret_unconfigured(client, monkeypatch):
    monkeypatch.delenv("HANDOFF_SHARED_SECRET")
    response = await client.get("/internal/health", headers=AUTH)
    assert response.status_code == 403


def test_internal_routes_absent_in_local_mode(monkeypatch):
    monkeypatch.setenv("MIMB_MODE", "local")
    from mastodon_is_my_blog import main

    assert not any(
        getattr(route, "path", "").startswith("/internal") for route in main.app.routes
    )


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/internal/health", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {"mode": "local", "ok": True}


# --- Provision idempotency (§6 item 3) ---


@pytest.mark.asyncio
async def test_provision_twice_creates_one_meta_account(client):
    first = await client.post(
        "/internal/tenants/7/provision", json={"job_id": 1}, headers=AUTH
    )
    assert first.status_code == 200
    assert first.json()["created"] is True

    second = await client.post(
        "/internal/tenants/7/provision", json={"job_id": 2}, headers=AUTH
    )
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["meta_account_id"] == first.json()["meta_account_id"]


# --- Sync / rebuild 202 semantics ---


@pytest.mark.asyncio
async def test_sync_skips_unprovisioned_tenant(client):
    response = await client.post(
        "/internal/tenants/99/sync", json={"job_id": 1}, headers=AUTH
    )
    assert response.status_code == 202
    assert response.json()["status"] == "skipped"


@pytest.mark.asyncio
async def test_sync_skips_tenant_with_no_identities(client):
    await client.post(
        "/internal/tenants/5/provision", json={"job_id": 1}, headers=AUTH
    )
    response = await client.post(
        "/internal/tenants/5/sync", json={"job_id": 2}, headers=AUTH
    )
    assert response.status_code == 202
    assert response.json()["status"] == "skipped"


@pytest.mark.asyncio
async def test_sync_starts_for_connected_tenant(client, two_tenants_seeded, monkeypatch):
    monkeypatch.setattr(internal, "sync_all_identities", AsyncMock(return_value=[]))
    response = await client.post(
        "/internal/tenants/1/sync", json={"job_id": 3}, headers=AUTH
    )
    assert response.status_code == 202
    assert response.json() == {"status": "started"}


def test_count_new_posts_sums_timeline_new():
    results = [
        {"a@x": {"timeline": {"status": "success", "count": 5, "new": 3}}},
        {"b@x": {"timeline": {"status": "skipped"}, "notifications": {}}},
        {"c@x": {"status": "error", "error": "boom"}},  # no timeline key
        {"d@x": {"timeline": {"new": 2}}},
    ]
    assert internal.count_new_posts(results) == 5


@pytest.mark.asyncio
async def test_sync_rebuilds_blog_only_when_new_posts(monkeypatch):
    """After a control-plane sync, the blog rebuilds iff new own-posts landed —
    so content published after Connect Account shows up without a manual rebuild."""
    rebuilt: list[int] = []

    async def fake_rebuild(tenant_id, meta_account_id):
        rebuilt.append(tenant_id)

    meta = make_meta_account(meta_id=7)
    monkeypatch.setattr(internal, "rebuild_blog_for_tenant", fake_rebuild)

    # No new posts -> no rebuild.
    monkeypatch.setattr(
        internal, "sync_all_identities",
        AsyncMock(return_value=[{"a@x": {"timeline": {"new": 0}}}]),
    )
    internal.syncing_tenants.add(1)
    await internal.sync_and_maybe_rebuild(1, meta)
    assert rebuilt == []
    assert 1 not in internal.syncing_tenants  # released even without a rebuild

    # New posts -> rebuild fires once.
    monkeypatch.setattr(
        internal, "sync_all_identities",
        AsyncMock(return_value=[{"a@x": {"timeline": {"new": 4}}}]),
    )
    internal.syncing_tenants.add(1)
    await internal.sync_and_maybe_rebuild(1, meta)
    assert rebuilt == [1]
    assert 1 not in internal.syncing_tenants


# --- Neutral limits push (sprint 04: suspension + quotas) ---


@pytest.mark.asyncio
async def test_limits_push_creates_meta_account_and_stores_values(client):
    # Push before the tenant ever visits: get-or-create.
    response = await client.put(
        "/internal/tenants/11/limits",
        json={"job_id": 1, "enabled": False, "max_identities": 2, "max_storage_bytes": 1000},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "max_identities": 2, "max_storage_bytes": 1000}

    meta = await tenant_export.get_tenant_meta_account("tenant_11")
    assert meta is not None
    assert meta.enabled is False
    assert meta.max_identities == 2

    # A second push (unsuspend, plan upgrade) overwrites.
    response = await client.put(
        "/internal/tenants/11/limits",
        json={"job_id": 2, "enabled": True, "max_identities": 5, "max_storage_bytes": None},
        headers=AUTH,
    )
    assert response.json() == {"enabled": True, "max_identities": 5, "max_storage_bytes": None}


@pytest.mark.asyncio
async def test_sync_skipped_when_disabled(client, two_tenants_seeded):
    await client.put(
        "/internal/tenants/1/limits",
        json={"job_id": 1, "enabled": False},
        headers=AUTH,
    )
    response = await client.post(
        "/internal/tenants/1/sync", json={"job_id": 2}, headers=AUTH
    )
    assert response.status_code == 202
    assert response.json() == {"status": "skipped", "reason": "tenant disabled"}


@pytest.mark.asyncio
async def test_sync_skipped_over_storage_limit(client, two_tenants_seeded):
    # Tenant 1 has cached posts; a 1-byte ceiling is instantly exceeded.
    # Pause-don't-delete: the response says why, nothing is removed.
    await client.put(
        "/internal/tenants/1/limits",
        json={"job_id": 1, "enabled": True, "max_storage_bytes": 1},
        headers=AUTH,
    )
    response = await client.post(
        "/internal/tenants/1/sync", json={"job_id": 2}, headers=AUTH
    )
    assert response.status_code == 202
    assert response.json() == {"status": "skipped", "reason": "storage limit exceeded"}

    usage = await client.get("/internal/tenants/1/usage", headers=AUTH)
    assert usage.json()["bytes"] > 0  # data intact


@pytest.mark.asyncio
async def test_sync_runs_under_storage_limit(client, two_tenants_seeded, monkeypatch):
    monkeypatch.setattr(internal, "sync_all_identities", AsyncMock(return_value=[]))
    await client.put(
        "/internal/tenants/1/limits",
        json={"job_id": 1, "enabled": True, "max_storage_bytes": 10_000_000},
        headers=AUTH,
    )
    response = await client.post(
        "/internal/tenants/1/sync", json={"job_id": 2}, headers=AUTH
    )
    assert response.status_code == 202
    assert response.json() == {"status": "started"}


@pytest.mark.asyncio
async def test_rebuild_blog_starts_and_skips(client, two_tenants_seeded):
    started = await client.post(
        "/internal/tenants/1/rebuild-blog", json={"job_id": 4}, headers=AUTH
    )
    assert started.status_code == 202
    assert started.json() == {"status": "started"}

    skipped = await client.post(
        "/internal/tenants/99/rebuild-blog", json={"job_id": 5}, headers=AUTH
    )
    assert skipped.status_code == 202
    assert skipped.json()["status"] == "skipped"


@pytest.mark.asyncio
async def test_rebuild_blog_payload_written(
    two_tenants_seeded, patch_async_session, tmp_path, monkeypatch
):
    patch_async_session(tenant_export, storm_export)
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path))
    # Keep the test off the real Eleventy project: fallback renderer path.
    monkeypatch.setenv("ELEVENTY_SITE_DIR", str(tmp_path / "no-eleventy"))
    monkeypatch.setenv("BLOG_DIR", str(tmp_path / "blogs"))
    await internal.rebuild_blog_for_tenant(1, 1)
    out_dir = tmp_path / "blog_tenant_1"
    assert (out_dir / "storms.json").exists()
    # The static blog got built too (fallback here; Eleventy in real deploys).
    assert (tmp_path / "blogs" / "tenant_1" / "index.html").exists()
    assert (out_dir / "blogroll.json").exists()
    storms = (out_dir / "storms.json").read_text(encoding="utf-8")
    assert "tenant one storm root" in storms
    assert "TENANT TWO SECRET" not in storms


# --- Export: isolation + bootability (§6 item 1, spec §3 notes) ---


def read_exported_db(zip_path: str, tmp_path) -> sqlite3.Connection:
    with zipfile.ZipFile(zip_path) as bundle:
        bundle.extract("app.db", tmp_path / "extracted")
    return sqlite3.connect(tmp_path / "extracted" / "app.db")


@pytest.mark.asyncio
async def test_export_contains_only_own_tenant_rows(
    client, two_tenants_seeded, tmp_path
):
    response = await client.post(
        "/internal/tenants/1/export", json={"job_id": 11}, headers=AUTH
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["bytes"] > 0

    with zipfile.ZipFile(payload["download_path"]) as bundle:
        names = set(bundle.namelist())
    assert {"app.db", "blog/storms.json", "blog/blogroll.json"} <= names

    conn = read_exported_db(payload["download_path"], tmp_path)
    try:
        contents = [
            row[0] for row in conn.execute("SELECT content FROM cached_posts")
        ]
        assert any("tenant one" in c for c in contents)
        assert not any("TENANT TWO" in c for c in contents)
        accts = [row[0] for row in conn.execute("SELECT acct FROM cached_accounts")]
        assert accts == ["f1@example.social"]
        identities = conn.execute("SELECT acct FROM mastodon_identities").fetchall()
        assert identities == [("one@example.social",)]
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_export_is_self_host_bootable(client, two_tenants_seeded, tmp_path):
    """The exported file must load under MIMB_MODE=local: the MetaAccount is
    renamed to 'default' and hosted tokens are stripped."""
    response = await client.post(
        "/internal/tenants/1/export", json={"job_id": 12}, headers=AUTH
    )
    payload = response.json()

    conn = read_exported_db(payload["download_path"], tmp_path)
    try:
        usernames = [
            row[0] for row in conn.execute("SELECT username FROM meta_accounts")
        ]
        assert usernames == ["default"]
        secrets = conn.execute(
            "SELECT access_token, client_secret FROM mastodon_identities"
        ).fetchall()
        assert secrets == [("", "")]
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_exported_db_renders_posts_in_local_mode(
    two_tenants_seeded, patch_async_session, tmp_path, monkeypatch
):
    """Acceptance test from the spec: point a local-mode instance's database
    at the exported file and assert the tenant's posts render."""
    patch_async_session(tenant_export, storm_export)
    zip_path = await tenant_export.build_tenant_export_zip(
        1, 1, "boot", tmp_path / "exports"
    )
    with zipfile.ZipFile(zip_path) as bundle:
        bundle.extract("app.db", tmp_path / "boot")

    # Point a local-mode session factory at the exported file, exactly as a
    # self-hosted install's DB_URL would, and drive the real code paths.
    exported_engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'boot' / 'app.db').as_posix()}"
    )
    factory = async_sessionmaker(exported_engine, expire_on_commit=False)
    try:
        async with factory() as session:
            meta = (
                await session.execute(
                    select(MetaAccount).where(MetaAccount.username == "default")
                )
            ).scalar_one()
            posts = (
                (
                    await session.execute(
                        select(CachedPost).where(CachedPost.meta_account_id == meta.id)
                    )
                )
                .scalars()
                .all()
            )
            assert {p.id for p in posts} == {
                "storm-root",
                "storm-reply",
                "shared-post-id",
            }
            identity = (await session.execute(select(MastodonIdentity))).scalar_one()
            assert identity.access_token == ""

        # The blog render path: local mode's unscoped storm loader.
        monkeypatch.setattr(storm_export, "async_session", factory)
        storms = await storm_export.load_storm_export_data()
        assert storms["storm_count"] == 1
        assert "tenant one storm root" in storms["storms"][0]["content_text"]
    finally:
        await exported_engine.dispose()


@pytest.mark.asyncio
async def test_export_is_idempotent_per_job(client, two_tenants_seeded):
    first = await client.post(
        "/internal/tenants/1/export", json={"job_id": 13}, headers=AUTH
    )
    second = await client.post(
        "/internal/tenants/1/export", json={"job_id": 13}, headers=AUTH
    )
    assert first.json()["download_path"] == second.json()["download_path"]


@pytest.mark.asyncio
async def test_export_unprovisioned_tenant_404(client):
    response = await client.post(
        "/internal/tenants/99/export", json={"job_id": 14}, headers=AUTH
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_admin_upgrade_migrates_and_reports_version(client, monkeypatch):
    calls = []

    async def fake_init_db():
        calls.append(True)

    import mastodon_is_my_blog.store as store_module

    monkeypatch.setattr(store_module, "init_db", fake_init_db)

    response = await client.post("/internal/admin/upgrade", json={"job_id": 31}, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "upgraded"
    assert body["version"]
    assert body["steps"]
    assert calls  # the in-band migration actually ran

    # Like everything on /internal: no bearer, no service.
    response = await client.post("/internal/admin/upgrade", json={"job_id": 31})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_export_download_streams_the_zip(client, two_tenants_seeded):
    await client.post("/internal/tenants/1/export", json={"job_id": 21}, headers=AUTH)

    response = await client.get("/internal/tenants/1/exports/21/download", headers=AUTH)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.content[:2] == b"PK"  # zip magic

    # Wrong job id: nothing built under that name.
    response = await client.get("/internal/tenants/1/exports/999/download", headers=AUTH)
    assert response.status_code == 404

    # Path-traversal shaped job ids are rejected: dotted ids hit our 400
    # guard, and encoded slashes never even match the route (404).
    response = await client.get("/internal/tenants/1/exports/../download", headers=AUTH)
    assert response.status_code in (400, 404)
    response = await client.get(
        "/internal/tenants/1/exports/..%2F..%2Fetc/download", headers=AUTH
    )
    assert response.status_code in (400, 404)


# --- Purge: isolation + idempotency (§6 items 1, 3) ---


@pytest.mark.asyncio
async def test_purge_removes_tenant_and_spares_neighbor(client, two_tenants_seeded):
    first = await client.request(
        "DELETE", "/internal/tenants/1", json={"job_id": 21}, headers=AUTH
    )
    assert first.status_code == 200
    assert first.json() == {"status": "purged"}

    again = await client.request(
        "DELETE", "/internal/tenants/1", json={"job_id": 21}, headers=AUTH
    )
    assert again.json() == {"status": "already_gone"}

    # Tenant 2 untouched, tenant 1 gone — including identities (tokens).
    export_two = await client.post(
        "/internal/tenants/2/export", json={"job_id": 22}, headers=AUTH
    )
    assert export_two.status_code == 200
    export_one = await client.post(
        "/internal/tenants/1/export", json={"job_id": 23}, headers=AUTH
    )
    assert export_one.status_code == 404


@pytest.mark.asyncio
async def test_purge_deletes_all_scoped_rows(
    two_tenants_seeded, patch_async_session, db_session
):
    patch_async_session(tenant_export)
    assert await tenant_export.purge_tenant_data("tenant_1") is True

    remaining_identities = (
        (await db_session.execute(select(MastodonIdentity))).scalars().all()
    )
    assert [i.meta_account_id for i in remaining_identities] == [2]
    remaining_posts = (await db_session.execute(select(CachedPost))).scalars().all()
    assert {p.meta_account_id for p in remaining_posts} == {2}
    metas = (await db_session.execute(select(MetaAccount))).scalars().all()
    assert [m.username for m in metas] == ["tenant_2"]


# --- Usage ---


@pytest.mark.asyncio
async def test_usage_is_tenant_scoped_and_approximate(client, two_tenants_seeded):
    one = (await client.get("/internal/tenants/1/usage", headers=AUTH)).json()
    two = (await client.get("/internal/tenants/2/usage", headers=AUTH)).json()
    unknown = (await client.get("/internal/tenants/99/usage", headers=AUTH)).json()

    assert one["approximate"] is True
    assert one["bytes"] > two["bytes"] > 0  # tenant 1 has three posts vs one
    assert unknown["bytes"] == 0
