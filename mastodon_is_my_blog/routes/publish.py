"""Local-mode publish endpoints: build the Eleventy blog into ./docs,
scaffold a GitHub Pages workflow, and git commit+push. Hosted tenants get
automatic rebuilds instead (blog_build.py), so everything here 404s in
server mode.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from mastodon_is_my_blog import blog_publish, tenancy
from mastodon_is_my_blog.queries import get_current_meta_account
from mastodon_is_my_blog.store import MetaAccount

router = APIRouter(prefix="/api/admin/publish", tags=["publish"])
preview_router = APIRouter(tags=["publish"])


def require_local_mode() -> None:
    if tenancy.is_server_mode():
        raise HTTPException(404, "Publishing is handled automatically in hosted mode")


@router.get("/status")
async def publish_status(meta: MetaAccount = Depends(get_current_meta_account)) -> dict:
    _ = meta
    require_local_mode()
    return await asyncio.to_thread(blog_publish.get_publish_status)


@router.post("/build")
async def build_blog(meta: MetaAccount = Depends(get_current_meta_account)) -> dict:
    _ = meta
    require_local_mode()
    return await blog_publish.build_docs()


class PagesWorkflowRequest(BaseModel):
    overwrite: bool = False


@router.post("/pages-workflow")
async def create_pages_workflow(
    body: PagesWorkflowRequest,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    _ = meta
    require_local_mode()
    status = blog_publish.get_publish_status()
    if not status["git_repo"]:
        raise HTTPException(400, f"{status['repo_root']} is not a git repository")
    return await asyncio.to_thread(blog_publish.create_pages_workflow, body.overwrite)


class PushRequest(BaseModel):
    message: str = "Publish blog"


@router.post("/push")
async def push_blog(
    body: PushRequest,
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    _ = meta
    require_local_mode()
    result = await asyncio.to_thread(blog_publish.git_publish, body.message)
    if not result.get("ok"):
        raise HTTPException(400, result.get("detail", "Publish failed"))
    return result


@preview_router.get("/blog-preview")
async def blog_preview_root() -> RedirectResponse:
    require_local_mode()
    return RedirectResponse(url="/blog-preview/")


@preview_router.get("/blog-preview/{full_path:path}")
async def blog_preview(full_path: str) -> FileResponse:
    """Serve the locally built docs/ so 'preview before you push' needs no
    extra server or make target."""
    require_local_mode()
    root = blog_publish.docs_output_dir().resolve()
    if not root.exists():
        raise HTTPException(404, "No built blog yet — use Admin → Publish → Build")
    target = (root / full_path).resolve() if full_path else root
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(404, "Not found") from exc
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(str(target))
