import json
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select

from mastodon_is_my_blog.datetime_helpers import utc_now
from mastodon_is_my_blog.mastodon_apis.masto_client import (
    client_from_identity,
)
from mastodon_is_my_blog.models import (
    DraftIn,
    DraftOut,
    EditIn,
    PostIn,
    PublishTreeIn,
    SpellcheckIn,
    SpellcheckMatch,
    SpellcheckOut,
    SplitChunk,
    SplitNodeIn,
)
from mastodon_is_my_blog.storm_splitter import storm_split
from mastodon_is_my_blog.queries import (
    get_current_meta_account,
    sync_user_timeline_for_identity,
)
from mastodon_is_my_blog.store import (
    Draft,
    MastodonIdentity,
    MetaAccount,
    async_session,
)

posts_router = APIRouter(prefix="/api/posts", tags=["writing"])
drafts_router = APIRouter(prefix="/api/drafts", tags=["drafts"])


@posts_router.post("/{status_id}/edit")
async def edit(
    status_id: str,
    payload: EditIn,
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
    return m.status_update(
        status_id,
        status=payload.status,
        spoiler_text=payload.spoiler_text,
    )


@posts_router.post("")
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

    await sync_user_timeline_for_identity(meta_id=meta.id, identity=identity, force=True)

    return resp


# --- Draft CRUD ---


@drafts_router.get("", response_model=list[DraftOut])
async def list_drafts(
    meta: MetaAccount = Depends(get_current_meta_account),
):
    async with async_session() as session:
        stmt = (
            select(Draft)
            .where(
                and_(
                    Draft.meta_account_id == meta.id,
                    Draft.published_at.is_(None),
                )
            )
            .order_by(Draft.updated_at.desc())
        )
        drafts = (await session.execute(stmt)).scalars().all()
        return [DraftOut.model_validate(d) for d in drafts]


@drafts_router.get("/{draft_id}", response_model=DraftOut)
async def get_draft(
    draft_id: int,
    meta: MetaAccount = Depends(get_current_meta_account),
):
    async with async_session() as session:
        stmt = select(Draft).where(and_(Draft.id == draft_id, Draft.meta_account_id == meta.id))
        draft = (await session.execute(stmt)).scalar_one_or_none()
        if not draft:
            raise HTTPException(404, "Draft not found")
        return DraftOut.model_validate(draft)


@drafts_router.post("", response_model=DraftOut)
async def create_draft(
    payload: DraftIn,
    meta: MetaAccount = Depends(get_current_meta_account),
):
    async with async_session() as session:
        draft = Draft(
            meta_account_id=meta.id,
            identity_id=payload.identity_id,
            reply_to_status_id=payload.reply_to_status_id,
            title=payload.title,
            tree_json=payload.tree_json,
            editor_engine=payload.editor_engine,
            language=payload.language,
        )
        session.add(draft)
        await session.commit()
        await session.refresh(draft)
        return DraftOut.model_validate(draft)


@drafts_router.put("/{draft_id}", response_model=DraftOut)
async def update_draft(
    draft_id: int,
    payload: DraftIn,
    meta: MetaAccount = Depends(get_current_meta_account),
):
    async with async_session() as session:
        stmt = select(Draft).where(and_(Draft.id == draft_id, Draft.meta_account_id == meta.id))
        draft = (await session.execute(stmt)).scalar_one_or_none()
        if not draft:
            raise HTTPException(404, "Draft not found")

        draft.title = payload.title
        draft.tree_json = payload.tree_json
        draft.editor_engine = payload.editor_engine
        draft.language = payload.language
        draft.identity_id = payload.identity_id
        draft.reply_to_status_id = payload.reply_to_status_id
        draft.updated_at = utc_now()

        await session.commit()
        await session.refresh(draft)
        return DraftOut.model_validate(draft)


@drafts_router.delete("/{draft_id}", status_code=204)
async def delete_draft(
    draft_id: int,
    meta: MetaAccount = Depends(get_current_meta_account),
):
    async with async_session() as session:
        stmt = select(Draft).where(and_(Draft.id == draft_id, Draft.meta_account_id == meta.id))
        draft = (await session.execute(stmt)).scalar_one_or_none()
        if not draft:
            raise HTTPException(404, "Draft not found")
        await session.delete(draft)
        await session.commit()


@drafts_router.post("/{draft_id}/split", response_model=list[SplitChunk])
async def split_node(
    draft_id: int,
    payload: SplitNodeIn,
    meta: MetaAccount = Depends(get_current_meta_account),
):
    async with async_session() as session:
        stmt = select(Draft).where(and_(Draft.id == draft_id, Draft.meta_account_id == meta.id))
        draft = (await session.execute(stmt)).scalar_one_or_none()
        if not draft:
            raise HTTPException(404, "Draft not found")

        nodes = json.loads(draft.tree_json or "[]")
        node = next((n for n in nodes if n.get("client_id") == payload.client_id), None)
        if not node:
            raise HTTPException(404, "Node not found")

    chunks = storm_split(
        node.get("body", ""),
        max_chars=payload.max_chars,
        add_counter=payload.add_counter,
    )
    return [SplitChunk(body=body, order=i) for i, body in enumerate(chunks)]


@drafts_router.post("/{draft_id}/publish", response_model=DraftOut)
async def publish_draft(
    draft_id: int,
    payload: PublishTreeIn,
    meta: MetaAccount = Depends(get_current_meta_account),
):
    async with async_session() as session:
        stmt = select(Draft).where(and_(Draft.id == draft_id, Draft.meta_account_id == meta.id))
        draft = (await session.execute(stmt)).scalar_one_or_none()
        if not draft:
            raise HTTPException(404, "Draft not found")

        id_stmt = select(MastodonIdentity).where(
            and_(
                MastodonIdentity.id == payload.identity_id,
                MastodonIdentity.meta_account_id == meta.id,
            )
        )
        identity = (await session.execute(id_stmt)).scalar_one_or_none()
        if not identity:
            raise HTTPException(404, "Identity not found or unauthorized")

        nodes = json.loads(draft.tree_json or "[]")
        if not nodes:
            raise HTTPException(400, "Draft has no content")

        m = client_from_identity(identity)

        # Walk nodes in order, chain in_reply_to_id
        reply_to_id = draft.reply_to_status_id
        root_status_id: str | None = None

        for node in nodes:
            body = node.get("body", "").strip()
            if not body:
                continue
            resp = m.status_post(
                status=body,
                visibility=node.get("visibility", "public"),
                spoiler_text=node.get("spoiler_text") or None,
                in_reply_to_id=reply_to_id,
            )
            posted_id = resp["id"] if isinstance(resp, dict) else resp.id
            if root_status_id is None:
                root_status_id = posted_id
            reply_to_id = posted_id

        draft.published_at = utc_now()
        draft.published_root_status_id = root_status_id
        await session.commit()
        await session.refresh(draft)

        await sync_user_timeline_for_identity(meta_id=meta.id, identity=identity, force=True)

        return DraftOut.model_validate(draft)


LANGUAGETOOL_URL = os.environ.get("LANGUAGETOOL_URL", "http://localhost:8081/v2/check")


@drafts_router.post("/spellcheck", response_model=SpellcheckOut)
async def spellcheck(
    payload: SpellcheckIn,
    meta: MetaAccount = Depends(get_current_meta_account),  # pylint: disable=unused-argument
):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                LANGUAGETOOL_URL,
                data={"text": payload.text, "language": payload.language},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError as exc:
        raise HTTPException(503, "LanguageTool not available") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"LanguageTool error: {exc.response.status_code}") from exc

    matches = [
        SpellcheckMatch(
            message=m["message"],
            offset=m["offset"],
            length=m["length"],
            replacements=[r["value"] for r in m.get("replacements", [])[:5]],
            rule_id=m["rule"]["id"],
        )
        for m in data.get("matches", [])
    ]
    return SpellcheckOut(matches=matches)
