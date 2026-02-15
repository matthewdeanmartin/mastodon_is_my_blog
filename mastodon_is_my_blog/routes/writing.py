from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select

from mastodon_is_my_blog.mastodon_apis.masto_client import (
    client_from_identity,
)
from mastodon_is_my_blog.models import EditIn, PostIn
from mastodon_is_my_blog.queries import (
    get_current_meta_account,
    sync_user_timeline_for_identity,
)
from mastodon_is_my_blog.store import (
    MastodonIdentity,
    MetaAccount,
    async_session,
)

router = APIRouter(prefix="/api/posts", tags=["writing"])


@router.post("/{status_id}/edit")
async def edit(
    status_id: str,
    payload: EditIn,
    identity_id: int = Query(...),
    meta: MetaAccount = Depends(get_current_meta_account),
):
    async with async_session() as session:
        # Lookup identity and verify ownership
        stmt = select(MastodonIdentity).where(
            and_(
                MastodonIdentity.id == identity_id,
                MastodonIdentity.meta_account_id == meta.id,
            )
        )
        identity = (await session.execute(stmt)).scalar_one_or_none()

        if not identity:
            raise HTTPException(404, "Identity not found or unauthorized")

    if not payload.status.strip():
        raise HTTPException(400, "Empty post")

    m = client_from_identity(identity)
    return m.status_update(
        status_id,
        status=payload.status,
        spoiler_text=payload.spoiler_text,
    )


@router.post("")
async def create_post(
    payload: PostIn,
    identity_id: int = Query(...),
    meta: MetaAccount = Depends(get_current_meta_account),
):
    async with async_session() as session:
        stmt = select(MastodonIdentity).where(
            and_(
                MastodonIdentity.id == identity_id,
                MastodonIdentity.meta_account_id == meta.id,
            )
        )
        identity = (await session.execute(stmt)).scalar_one_or_none()

        if not identity:
            raise HTTPException(404, "Identity not found or unauthorized")

    if not payload.status.strip():
        raise HTTPException(400, "Empty post")

    m = client_from_identity(identity)
    resp = m.status_post(
        status=payload.status,
        visibility=payload.visibility,
        spoiler_text=payload.spoiler_text,
    )

    # Trigger immediate sync for this specific identity
    await sync_user_timeline_for_identity(
        meta_id=meta.id, identity=identity, force=True
    )

    return resp
