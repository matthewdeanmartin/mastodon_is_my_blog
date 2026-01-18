from fastapi import APIRouter, HTTPException

from mastodon_is_my_blog.mastodon_apis.masto_client import (
    client,
    get_default_client,
)
from mastodon_is_my_blog.models import EditIn, PostIn
from mastodon_is_my_blog.queries import (
    sync_user_timeline,
)
from mastodon_is_my_blog.store import (
    get_token,
)

router = APIRouter(prefix="/api/posts", tags=["writing"])


@router.post("{status_id}/edit")
async def edit(status_id: str, payload: EditIn):
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    m = client(token)
    if not payload.status.strip():
        raise HTTPException(400, "Empty post")

    return m.status_update(
        status_id,
        status=payload.status,
        spoiler_text=payload.spoiler_text,
    )


@router.post("")
async def create_post(payload: PostIn):
    token = await get_token()
    if not token:
        raise HTTPException(401, "Not connected")
    m = await get_default_client()

    if not payload.status.strip():
        raise HTTPException(400, "Empty post")
    resp = m.status_post(
        status=payload.status,
        visibility=payload.visibility,
        spoiler_text=payload.spoiler_text,
    )
    # Trigger immediate sync
    await sync_user_timeline(force=True)
    return resp
