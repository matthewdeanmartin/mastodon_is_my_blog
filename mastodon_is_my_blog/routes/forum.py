"""Forum threads endpoint — groups cached posts into threaded discussions."""

import base64
import logging
from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, select

from mastodon_is_my_blog import duck
from mastodon_is_my_blog.queries import get_current_meta_account
from mastodon_is_my_blog.store import (
    CachedAccount,
    MastodonIdentity,
    MetaAccount,
    async_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/forum", tags=["forum"])

DEFAULT_LIMIT = 25
MAX_LIMIT = 100


def encode_forum_cursor(ts: datetime, root_id: str) -> str:
    raw = f"{ts.isoformat()}|{root_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode("ascii")


def decode_forum_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode()
        iso, rid = raw.split("|", 1)
        return datetime.fromisoformat(iso), rid
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "Invalid cursor") from exc


def instance_from_acct(acct: str, identity_base_url: str) -> str:
    """Extract instance domain from user@instance or local acct."""
    if "@" in acct:
        return acct.split("@", 1)[1]
    parsed = urlparse(identity_base_url)
    return parsed.hostname or identity_base_url


@router.get("/threads")
async def get_forum_threads(
    identity_id: int = Query(...),
    top_filter: str = Query(
        "recent",
        enum=["questions", "friends_started", "popular", "recent", "mine", "participating"],
    ),
    hashtag: list[str] = Query(default=[]),
    uncommon_word: list[str] = Query(default=[]),
    root_instance: list[str] = Query(default=[]),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    before: str | None = Query(None),
    include_content_hub: bool = Query(False),
    meta: MetaAccount = Depends(get_current_meta_account),
) -> dict:
    empty = {"items": [], "next_cursor": None, "facets": {"hashtags": [], "uncommon_words": [], "root_instances": []}}

    async with async_session() as session:
        identity_stmt = select(MastodonIdentity).where(
            and_(
                MastodonIdentity.id == identity_id,
                MastodonIdentity.meta_account_id == meta.id,
            )
        )
        identity = (await session.execute(identity_stmt)).scalar_one_or_none()
        if identity is None:
            return empty

        my_acct = identity.acct
        identity_base_url = identity.api_base_url

        following_stmt = select(CachedAccount.acct, CachedAccount.id, CachedAccount.display_name, CachedAccount.avatar).where(
            and_(
                CachedAccount.meta_account_id == meta.id,
                CachedAccount.mastodon_identity_id == identity_id,
                CachedAccount.is_following.is_(True),
            )
        )
        following_rows = (await session.execute(following_stmt)).all()

    following_accts: set[str] = {r.acct for r in following_rows}

    # Fetch pre-aggregated thread summaries from DuckDB
    raw_summaries = await duck.forum_thread_summaries(meta.id, identity_id, include_content_hub)

    thread_summaries = []
    for t in raw_summaries:
        root_acct = t["author_acct"]
        root_instance_domain = instance_from_acct(root_acct, identity_base_url)

        i_am_author = root_acct == my_acct
        i_am_participating = not i_am_author and my_acct in t.get("participants", set())

        latest_reply_str = t["latest_reply_at"]
        latest_reply_dt = datetime.fromisoformat(latest_reply_str) if latest_reply_str else None
        root_created_dt = datetime.fromisoformat(t["root_created_at"]) if t["root_created_at"] else None

        thread_summaries.append(
            {
                "root_id": t["root_id"],
                "reply_count": t["reply_count"],
                "unique_participant_count": t["unique_participants"],
                "latest_reply_at": latest_reply_dt,
                "root_created_at": root_created_dt,
                "root_acct": root_acct,
                "root_content": t["root_content"],
                "root_tags_json": t["root_tags"],
                "root_is_partial": t["root_is_partial"],
                "root_instance_domain": root_instance_domain,
                "tags": t["tags"],
                "uncommon_words": t["uncommon_words"],
                "has_question": t["has_question"],
                "author_is_friend": root_acct in following_accts,
                "i_am_author": i_am_author,
                "i_am_participating": i_am_participating,
                "friend_reply_count": 0,
                "friend_repliers": [],
            }
        )

    # Compute friend reply counts — only needed for "friends_started" / "popular" views
    # but we compute for all so the facets are accurate
    if following_accts:
        all_root_ids = [t["root_id"] for t in thread_summaries]
        friend_counts = await duck.forum_friend_reply_counts(meta.id, identity_id, all_root_ids, following_accts)
        for t in thread_summaries:
            t["friend_reply_count"] = friend_counts.get(t["root_id"], 0)

    # Build friend replier avatars for display (top 5 per thread)
    # Only do this for the page we'll actually serve to avoid O(N) work
    # We defer this to after filtering/sorting

    # Apply top filter
    if top_filter == "questions":
        thread_summaries = [t for t in thread_summaries if t["has_question"]]
    elif top_filter == "friends_started":
        thread_summaries = [t for t in thread_summaries if t["author_is_friend"]]
    elif top_filter == "mine":
        thread_summaries = [t for t in thread_summaries if t["i_am_author"]]
    elif top_filter == "participating":
        thread_summaries = [t for t in thread_summaries if t["i_am_participating"]]

    # Compute facets over the filtered set (stable denominator — before chip filters)
    hashtag_counts: dict[str, int] = {}
    word_counts: dict[str, int] = {}
    instance_counts: dict[str, int] = {}

    for t in thread_summaries:
        for tag in t["tags"]:
            hashtag_counts[tag] = hashtag_counts.get(tag, 0) + 1
        for word in t["uncommon_words"]:
            word_counts[word] = word_counts.get(word, 0) + 1
        inst = t["root_instance_domain"]
        instance_counts[inst] = instance_counts.get(inst, 0) + 1

    facets = {
        "hashtags": sorted(
            [{"tag": k, "count": v} for k, v in hashtag_counts.items()],
            key=lambda x: -x["count"],
        )[:20],
        "uncommon_words": sorted(
            [{"word": k, "thread_count": v} for k, v in word_counts.items() if v >= 2],
            key=lambda x: -x["thread_count"],
        )[:20],
        "root_instances": sorted(
            [{"instance": k, "count": v} for k, v in instance_counts.items()],
            key=lambda x: -x["count"],
        )[:20],
    }

    # Apply facet chip filters (AND across types, OR within same type)
    if hashtag:
        hashtag_set = {h.lower() for h in hashtag}
        thread_summaries = [t for t in thread_summaries if t["tags"] & hashtag_set]
    if uncommon_word:
        word_set = {w.lower() for w in uncommon_word}
        thread_summaries = [t for t in thread_summaries if set(t["uncommon_words"]) & word_set]
    if root_instance:
        instance_set = {i.lower() for i in root_instance}
        thread_summaries = [t for t in thread_summaries if t["root_instance_domain"].lower() in instance_set]

    # Sort
    if top_filter == "popular":
        thread_summaries.sort(key=lambda t: -t["friend_reply_count"])
    else:
        thread_summaries.sort(
            key=lambda t: t["latest_reply_at"] or t["root_created_at"] or datetime.min,
            reverse=True,
        )

    # Cursor pagination
    if before:
        cursor_ts, cursor_rid = decode_forum_cursor(before)
        filtered = []
        past_cursor = False
        for t in thread_summaries:
            sort_ts = t["latest_reply_at"] or t["root_created_at"]
            if not past_cursor:
                if sort_ts is not None and (sort_ts < cursor_ts or (sort_ts == cursor_ts and t["root_id"] < cursor_rid)):
                    past_cursor = True
                else:
                    continue
            if past_cursor:
                filtered.append(t)
        thread_summaries = filtered

    page = thread_summaries[:limit]
    next_cursor = None
    if len(thread_summaries) > limit:
        last = page[-1]
        sort_ts = last["latest_reply_at"] or last["root_created_at"]
        if sort_ts:
            next_cursor = encode_forum_cursor(sort_ts, last["root_id"])

    items = []
    for t in page:
        sort_ts = t["latest_reply_at"] or t["root_created_at"]
        items.append(
            {
                "root_id": t["root_id"],
                "root_post": {
                    "id": t["root_id"],
                    "author_acct": t["root_acct"],
                    "author_display_name": "",
                    "author_avatar": "",
                    "author_instance": t["root_instance_domain"],
                    "content": t["root_content"],
                    "created_at": t["root_created_at"].isoformat() if t["root_created_at"] else None,
                    "has_question": t["has_question"],
                    "tags": [],
                },
                "reply_count": t["reply_count"],
                "friend_reply_count": t["friend_reply_count"],
                "friend_repliers": t["friend_repliers"],
                "latest_reply_at": t["latest_reply_at"].isoformat() if t["latest_reply_at"] else None,
                "root_is_partial": t["root_is_partial"],
            }
        )

    return {"items": items, "next_cursor": next_cursor, "facets": facets}
