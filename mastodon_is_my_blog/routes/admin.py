# mastodon_is_my_blog/routes/admin.py
import logging

from fastapi import Depends
from fastapi.routing import APIRouter
from sqlalchemy import select

from mastodon_is_my_blog.mastodon_apis.masto_client import (
    client,
    client_from_identity,
)
from mastodon_is_my_blog.queries import get_current_meta_account, sync_all_identities
from mastodon_is_my_blog.store import (
    MastodonIdentity,
    MetaAccount,
    async_session,
    get_last_sync,
)
from mastodon_is_my_blog.utils.perf import time_async_function

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/sync")
@time_async_function
async def trigger_sync(
    force: bool = True, meta: MetaAccount = Depends(get_current_meta_account)
) -> dict:
    res = await sync_all_identities(meta, force=force)
    return {"results": res}


@router.get("/identities")
async def list_identities(meta: MetaAccount = Depends(get_current_meta_account)):
    async with async_session() as session:
        stmt = select(MastodonIdentity).where(
            MastodonIdentity.meta_account_id == meta.id
        )
        res = (await session.execute(stmt)).scalars().all()
        return [{"id": i.id, "acct": i.acct, "base_url": i.api_base_url} for i in res]


@router.post("/identities")
async def add_identity(
    base_url: str,
    code: str,
    client_id: str,
    client_secret: str,
    meta: MetaAccount = Depends(get_current_meta_account),
):
    """
    Exchanges code for token and saves identity.
    (Simplified OAuth flow - normally requires redirect)
    """
    # Create temp client to exchange code
    m = client(base_url, client_id, client_secret)
    access_token = m.log_in(code=code, scopes=["read", "write"])
    me = m.account_verify_credentials()

    async with async_session() as session:
        new_id = MastodonIdentity(
            meta_account_id=meta.id,
            api_base_url=base_url,
            client_id=client_id,
            client_secret=client_secret,
            access_token=access_token,
            acct=me["acct"],
            account_id=str(me["id"]),
        )
        session.add(new_id)
        await session.commit()
    return {"status": "created", "acct": me["acct"]}


@router.get("/status")
async def admin_status() -> dict:
    """Get connection status and current user info"""

    # Try to get default identity
    current_user = None
    connected = False

    async with async_session() as session:
        stmt = select(MetaAccount).where(MetaAccount.username == "default")
        meta = (await session.execute(stmt)).scalar_one_or_none()

        if meta:
            stmt = (
                select(MastodonIdentity)
                .where(MastodonIdentity.meta_account_id == meta.id)
                .limit(1)
            )
            identity = (await session.execute(stmt)).scalar_one_or_none()

            if identity and identity.access_token:
                connected = True
                try:
                    m = client_from_identity(identity)
                    me = m.account_verify_credentials()
                    current_user = {
                        "acct": me["acct"],
                        "display_name": me["display_name"],
                        "avatar": me["avatar"],
                        "note": me.get("note", ""),
                    }
                except Exception as e:
                    logger.error(e)
                    logger.error(f"Failed to verify credentials: {e}")
                    connected = False

    last_sync = await get_last_sync()

    return {
        "connected": connected,
        "last_sync": last_sync.isoformat() if last_sync else None,
        "current_user": current_user,
    }
