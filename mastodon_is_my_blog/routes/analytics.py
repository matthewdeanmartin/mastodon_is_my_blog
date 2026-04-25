"""Analytics endpoints backed by DuckDB over the live SQLite file."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from mastodon_is_my_blog import duck
from mastodon_is_my_blog.queries import get_current_meta_account
from mastodon_is_my_blog.store import MetaAccount

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/hashtag-trends")
async def hashtag_trends(
    identity_id: int = Query(...),
    bucket: str = Query("week", pattern="^(day|week|month)$"),
    top: int = Query(20, ge=1, le=200),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> list[dict[str, Any]]:
    return await duck.hashtag_trends(meta.id, identity_id, bucket=bucket, top=top)


@router.get("/content-search")
async def content_search(
    identity_id: int = Query(...),
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(100, ge=1, le=1000),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> list[dict[str, Any]]:
    try:
        return await duck.content_regex_search(meta.id, identity_id, q, limit=limit)
    except Exception as e:  # DuckDB raises on invalid regex
        raise HTTPException(status_code=400, detail=f"invalid regex: {e}") from e


@router.get("/posting-heatmap")
async def posting_heatmap(
    identity_id: int = Query(...),
    author_acct: str | None = Query(None),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> list[dict[str, Any]]:
    return await duck.posting_heatmap(meta.id, identity_id, author_acct=author_acct)


@router.get("/top-reposters")
async def top_reposters(
    identity_id: int = Query(...),
    window_days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=500),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> list[dict[str, Any]]:
    return await duck.top_reposters(meta.id, identity_id, window_days=window_days, limit=limit)


@router.get("/notification-trends")
async def notification_trends(
    identity_id: int = Query(...),
    notification_type: str | None = Query(None),
    bucket: str = Query("day", pattern="^(day|week|month)$"),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict[str, list[dict[str, Any]]]:
    return await duck.notification_trends(meta.id, identity_id, notification_type=notification_type, bucket=bucket)


@router.get("/activity-calendar")
async def activity_calendar(
    identity_id: int = Query(...),
    author_acct: str | None = Query(None),
    years: int = Query(2, ge=1, le=5),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> list[dict[str, Any]]:
    return await duck.activity_calendar(meta.id, identity_id, author_acct=author_acct, years=years)
