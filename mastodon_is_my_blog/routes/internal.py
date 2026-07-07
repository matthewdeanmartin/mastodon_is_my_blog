"""Control-plane hand-off API (spec/paid_hosting/control_plane_handoff.md).

Service-to-service endpoints called by mimb_co's job worker — signup, Stripe,
and the operator console decide *that* things happen; these endpoints do them.
Mounted only when MIMB_MODE=server (main.py), so a local install 404s on all
of /internal/*.

Auth is a shared bearer secret (HANDOFF_SHARED_SECRET), not session cookies.

DEPLOY NOTE: this API must never be reachable from the public internet — the
reverse proxy must not forward /internal/* (and/or bind it to a second,
internal-only port). The bearer secret is defense in depth, not the boundary.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
from pathlib import Path

from fastapi import Depends, Header, HTTPException
from fastapi.routing import APIRouter
from pydantic import BaseModel

from mastodon_is_my_blog import tenancy, tenant_export
from mastodon_is_my_blog.queries import sync_all_identities

logger = logging.getLogger(__name__)


def get_export_dir() -> Path:
    return Path(os.environ.get("EXPORT_DIR", "exports"))


async def require_handoff_secret(
    authorization: str | None = Header(default=None),
) -> None:
    secret = os.environ.get("HANDOFF_SHARED_SECRET", "")
    if not secret:
        # Server mode fails fast at startup without the secret; this guards
        # any misconfigured mount from becoming an open door.
        raise HTTPException(403, "hand-off API not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(403, "missing bearer token")
    presented = authorization[len("Bearer ") :]
    if not hmac.compare_digest(presented, secret):
        raise HTTPException(403, "invalid bearer token")


router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_handoff_secret)],
)


class JobRef(BaseModel):
    job_id: int | str


# Keep strong references so fire-and-forget tasks aren't garbage-collected
# mid-flight (asyncio only holds weak refs to tasks).
background_tasks: set[asyncio.Task] = set()


def spawn_background(coro, *, label: str) -> None:
    task = asyncio.create_task(coro, name=label)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


@router.get("/health")
async def health() -> dict:
    return {"mode": tenancy.get_mode(), "ok": True}


@router.post("/admin/upgrade")
async def upgrade_server(body: JobRef) -> dict:
    """Upgrade this product server — LOCAL version of the op.

    Locally, "upgrade" means: the operator already has the new code running
    (pip/uv upgrade + restart is outside the process), so this endpoint does
    the in-band half — re-run idempotent schema migration and report what
    version is actually serving. The cloud version of this op will be an
    image rollout with real Alembic steps; the control-plane contract (one
    POST, returns version + steps) is what stays stable.
    """
    from mastodon_is_my_blog.__about__ import __version__
    from mastodon_is_my_blog.store import init_db

    await init_db()
    steps = ["schema migrated (idempotent create_all)"]
    logger.info("server upgrade requested job_id=%s -> version=%s", body.job_id, __version__)
    return {"status": "upgraded", "version": __version__, "steps": steps}


@router.post("/tenants/{tenant_id}/provision")
async def provision_tenant(tenant_id: int, body: JobRef) -> dict:
    username = tenancy.tenant_username(tenant_id)
    meta, created = await tenant_export.get_or_create_meta_account(username)
    logger.info(
        "provision tenant_id=%s job_id=%s -> meta_account_id=%s created=%s",
        tenant_id, body.job_id, meta.id, created,
    )
    return {"meta_account_id": meta.id, "created": created}


class LimitsPush(JobRef):
    """The control plane's neutral per-tenant limits (see MetaAccount). This
    server never sees plan names or lifecycle states — enabled + ceilings is
    the whole vocabulary. None means unlimited."""

    enabled: bool = True
    max_identities: int | None = None
    max_storage_bytes: int | None = None


@router.put("/tenants/{tenant_id}/limits")
async def push_tenant_limits(tenant_id: int, body: LimitsPush) -> dict:
    username = tenancy.tenant_username(tenant_id)
    meta = await tenant_export.set_tenant_limits(
        username,
        enabled=body.enabled,
        max_identities=body.max_identities,
        max_storage_bytes=body.max_storage_bytes,
    )
    logger.info(
        "limits pushed tenant_id=%s job_id=%s enabled=%s max_identities=%s max_storage_bytes=%s",
        tenant_id, body.job_id, meta.enabled, meta.max_identities, meta.max_storage_bytes,
    )
    return {
        "enabled": meta.enabled,
        "max_identities": meta.max_identities,
        "max_storage_bytes": meta.max_storage_bytes,
    }


@router.post("/tenants/{tenant_id}/sync", status_code=202)
async def trigger_tenant_sync(tenant_id: int, body: JobRef) -> dict:
    """Kick the existing in-process sync for the tenant's identities and
    return immediately — syncs can take minutes and the caller (mimb_co's
    worker) must not block its poll loop on them."""
    username = tenancy.tenant_username(tenant_id)
    meta = await tenant_export.get_tenant_meta_account(username)
    if meta is None:
        return {"status": "skipped", "reason": "tenant not provisioned"}
    if meta.enabled is False:
        return {"status": "skipped", "reason": "tenant disabled"}
    if meta.max_storage_bytes is not None:
        # Pause-don't-delete on storage breach: existing data stays, new
        # syncs stop until the limit rises or usage falls.
        usage = await tenant_export.tenant_usage_bytes(meta.id)
        if usage >= meta.max_storage_bytes:
            logger.info(
                "sync skipped tenant_id=%s: usage %s >= limit %s",
                tenant_id, usage, meta.max_storage_bytes,
            )
            return {"status": "skipped", "reason": "storage limit exceeded"}
    identity_ids = await tenant_export.tenant_identity_ids(meta.id)
    if not identity_ids:
        return {"status": "skipped", "reason": "no connected identities"}
    spawn_background(
        sync_all_identities(meta, force=True), label=f"sync-tenant-{tenant_id}"
    )
    logger.info("sync started tenant_id=%s job_id=%s", tenant_id, body.job_id)
    return {"status": "started"}


async def rebuild_blog_for_tenant(tenant_id: int, meta_account_id: int) -> None:
    """Produce the storm/blogroll export payloads under EXPORT_DIR (the export
    bundle picks them up) and build the tenant's static blog from them
    (blog_build.py — Eleventy when available, plain HTML otherwise), served at
    /blogs/tenant_{id}/."""
    from mastodon_is_my_blog.blog_build import build_tenant_blog
    from mastodon_is_my_blog.storm_export import (
        load_blogroll_export_data,
        load_storm_export_data,
        write_json_export,
    )

    out_dir = get_export_dir() / f"blog_tenant_{tenant_id}"
    storms = await load_storm_export_data(meta_account_id=meta_account_id)
    blogroll = await load_blogroll_export_data(meta_account_id=meta_account_id)
    write_json_export(out_dir / "storms.json", storms)
    write_json_export(out_dir / "blogroll.json", blogroll)
    built = await build_tenant_blog(tenant_id, meta_account_id)
    logger.info(
        "blog rebuilt for tenant_id=%s payloads=%s static=%s (%s)",
        tenant_id, out_dir, built["blog_path"], built["builder"],
    )


@router.post("/tenants/{tenant_id}/rebuild-blog", status_code=202)
async def trigger_rebuild_blog(tenant_id: int, body: JobRef) -> dict:
    username = tenancy.tenant_username(tenant_id)
    meta = await tenant_export.get_tenant_meta_account(username)
    if meta is None:
        return {"status": "skipped", "reason": "tenant not provisioned"}
    identity_ids = await tenant_export.tenant_identity_ids(meta.id)
    if not identity_ids:
        return {"status": "skipped", "reason": "no connected identities"}
    spawn_background(
        rebuild_blog_for_tenant(tenant_id, meta.id),
        label=f"rebuild-blog-tenant-{tenant_id}",
    )
    logger.info("rebuild-blog started tenant_id=%s job_id=%s", tenant_id, body.job_id)
    return {"status": "started"}


class ConnectMockIdentity(JobRef):
    """Dev-stack demo wiring: which mock instance and which seeded account."""

    base_url: str = "http://localhost:3000"
    username: str = "ada"


@router.post("/tenants/{tenant_id}/connect-mock-identity")
async def connect_mock_identity(tenant_id: int, body: ConnectMockIdentity) -> dict:
    """Connect a mastodon_mock account to the tenant WITHOUT the browser OAuth
    dance, then sync it and build the blog — all synchronously (the mock is
    local and small). This is how `mimb-co seed-demo` gets a demo blog with
    real content instead of an empty shell.

    Works only against mastodon_mock: its authorization codes are the
    self-describing `mockcode_{username}` (routers/oauth.py in that repo), so
    the exchange below fails against any real instance. Localhost-only as a
    second guard — this must never become a way to skip real consent.
    """
    import httpx

    from mastodon_is_my_blog.blog_build import build_tenant_blog
    from mastodon_is_my_blog.routes.admin import persist_identity

    base_url = body.base_url.rstrip("/")
    if not (base_url.startswith("http://localhost") or base_url.startswith("http://127.")):
        raise HTTPException(400, "connect-mock-identity only works against a local mastodon_mock")

    username = tenancy.tenant_username(tenant_id)
    meta, _ = await tenant_export.get_or_create_meta_account(username)

    async with httpx.AsyncClient(timeout=30) as http:
        app_resp = await http.post(
            f"{base_url}/api/v1/apps",
            data={"client_name": "mimb-demo", "redirect_uris": "urn:ietf:wg:oauth:2.0:oob", "scopes": "read write"},
        )
        app_resp.raise_for_status()
        app_info = app_resp.json()
        token_resp = await http.post(
            f"{base_url}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": f"mockcode_{body.username}",
                "client_id": app_info["client_id"],
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(502, f"mock token exchange failed for {body.username!r}: {token_resp.text[:200]}")
        access_token = token_resp.json()["access_token"]
        me_resp = await http.get(
            f"{base_url}/api/v1/accounts/verify_credentials",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        me_resp.raise_for_status()
        me = me_resp.json()

    await persist_identity(meta, base_url, app_info["client_id"], app_info["client_secret"], access_token, me)
    await sync_all_identities(meta, force=True)
    built = await build_tenant_blog(tenant_id, meta.id)
    logger.info(
        "mock identity connected tenant_id=%s acct=%s job_id=%s builder=%s",
        tenant_id, me.get("acct"), body.job_id, built["builder"],
    )
    return {"acct": me.get("acct"), "synced": True, "blog_path": built["blog_path"], "builder": built["builder"]}


@router.post("/tenants/{tenant_id}/export")
async def export_tenant(tenant_id: int, body: JobRef) -> dict:
    """Build the export bundle synchronously (fine at current scale): a zip of
    the tenant's rows as a standalone, local-mode-bootable SQLite file plus
    the storm/blog export payloads."""
    username = tenancy.tenant_username(tenant_id)
    meta = await tenant_export.get_tenant_meta_account(username)
    if meta is None:
        raise HTTPException(404, "tenant not provisioned")
    zip_path = await tenant_export.build_tenant_export_zip(
        meta.id, tenant_id, body.job_id, get_export_dir()
    )
    size = zip_path.stat().st_size
    logger.info(
        "export built tenant_id=%s job_id=%s path=%s bytes=%s",
        tenant_id, body.job_id, zip_path, size,
    )
    return {"download_path": str(zip_path), "bytes": size}


@router.get("/tenants/{tenant_id}/exports/{job_id}/download")
async def download_tenant_export(tenant_id: int, job_id: str) -> "FileResponse":
    """Stream a previously built export bundle to the control plane.

    The zip lives on THIS server's disk (EXPORT_DIR); mimb_co's customer-facing
    GET /api/export/{job_id}/download proxies through here so the customer
    never talks to this service directly. Naming must match
    tenant_export.build_tenant_export_zip: export_tenant_{tid}_{job_id}.zip.
    """
    from fastapi.responses import FileResponse

    if not job_id.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "invalid job id")
    zip_path = get_export_dir() / f"export_tenant_{tenant_id}_{job_id}.zip"
    if not zip_path.is_file():
        raise HTTPException(404, "export bundle not found — build it via POST .../export first")
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"mimb_export_tenant_{tenant_id}.zip",
    )


@router.delete("/tenants/{tenant_id}")
async def purge_tenant(tenant_id: int, body: JobRef) -> dict:
    """Purge everything scoped to the tenant, including encrypted Mastodon
    tokens (the GDPR-relevant part). Idempotent: purging a missing tenant is
    already_gone, not 404 — mimb_co's worker retries failed jobs."""
    username = tenancy.tenant_username(tenant_id)
    purged = await tenant_export.purge_tenant_data(username)
    logger.info(
        "purge tenant_id=%s job_id=%s result=%s",
        tenant_id, body.job_id, "purged" if purged else "already_gone",
    )
    return {"status": "purged" if purged else "already_gone"}


@router.get("/tenants/{tenant_id}/usage")
async def tenant_usage(tenant_id: int) -> dict:
    username = tenancy.tenant_username(tenant_id)
    meta = await tenant_export.get_tenant_meta_account(username)
    if meta is None:
        return {"bytes": 0, "approximate": True, "basis": "tenant not provisioned"}
    usage = await tenant_export.tenant_usage_bytes(meta.id)
    return {
        "bytes": usage,
        "approximate": True,
        "basis": "sum of cached post/account text payloads in shared-DB mode; "
        "excludes indexes and row overhead",
    }
