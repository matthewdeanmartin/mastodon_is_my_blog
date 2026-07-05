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


@router.post("/tenants/{tenant_id}/provision")
async def provision_tenant(tenant_id: int, body: JobRef) -> dict:
    username = tenancy.tenant_username(tenant_id)
    meta, created = await tenant_export.get_or_create_meta_account(username)
    logger.info(
        "provision tenant_id=%s job_id=%s -> meta_account_id=%s created=%s",
        tenant_id, body.job_id, meta.id, created,
    )
    return {"meta_account_id": meta.id, "created": created}


@router.post("/tenants/{tenant_id}/sync", status_code=202)
async def trigger_tenant_sync(tenant_id: int, body: JobRef) -> dict:
    """Kick the existing in-process sync for the tenant's identities and
    return immediately — syncs can take minutes and the caller (mimb_co's
    worker) must not block its poll loop on them."""
    username = tenancy.tenant_username(tenant_id)
    meta = await tenant_export.get_tenant_meta_account(username)
    if meta is None:
        return {"status": "skipped", "reason": "tenant not provisioned"}
    identity_ids = await tenant_export.tenant_identity_ids(meta.id)
    if not identity_ids:
        return {"status": "skipped", "reason": "no connected identities"}
    spawn_background(
        sync_all_identities(meta, force=True), label=f"sync-tenant-{tenant_id}"
    )
    logger.info("sync started tenant_id=%s job_id=%s", tenant_id, body.job_id)
    return {"status": "started"}


async def rebuild_blog_for_tenant(tenant_id: int, meta_account_id: int) -> None:
    """Produce the storm/blogroll export payloads and stash them under
    EXPORT_DIR. The Eleventy build + object-storage upload is Phase 2
    (server_side.md); this payload is its input."""
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
    logger.info("blog payload rebuilt for tenant_id=%s at %s", tenant_id, out_dir)


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
