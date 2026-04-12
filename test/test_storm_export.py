from datetime import datetime

from mastodon_is_my_blog.storm_export import (
    DEFAULT_MIN_TEXT_LENGTH,
    build_storm_exports,
    clean_mastodon_text,
)
from mastodon_is_my_blog.store import CachedPost, MastodonIdentity


def make_identity(
    *, identity_id: int, acct: str, api_base_url: str, account_id: str
) -> MastodonIdentity:
    return MastodonIdentity(
        id=identity_id,
        meta_account_id=1,
        api_base_url=api_base_url,
        client_id=f"client-{identity_id}",
        client_secret="secret",
        access_token="token",
        acct=acct,
        account_id=account_id,
    )


def make_post(
    *,
    post_id: str,
    author_acct: str,
    author_id: str,
    content: str,
    created_at: datetime,
    visibility: str = "public",
    in_reply_to_id: str | None = None,
    media_attachments: str | None = None,
) -> CachedPost:
    return CachedPost(
        id=post_id,
        meta_account_id=1,
        fetched_by_identity_id=1,
        content=content,
        created_at=created_at,
        visibility=visibility,
        author_acct=author_acct,
        author_id=author_id,
        is_reblog=False,
        is_reply=in_reply_to_id is not None,
        in_reply_to_id=in_reply_to_id,
        in_reply_to_account_id=None,
        has_media=bool(media_attachments),
        has_video=False,
        has_news=False,
        has_tech=False,
        has_link=False,
        has_question=False,
        media_attachments=media_attachments,
        tags=None,
        replies_count=0,
        reblogs_count=0,
        favourites_count=0,
    )


def test_clean_mastodon_text_strips_html_links_mentions_and_hashtags() -> None:
    html = """
    <p>Hello <a class="mention" href="https://mastodon.social/@alice">@alice</a></p>
    <p><a href="https://example.com">blog link</a> stays out.</p>
    <p><a class="hashtag" href="https://mastodon.social/tags/python">#python</a> done.</p>
    """

    assert clean_mastodon_text(html) == "Hello stays out. done."


def test_build_storm_exports_keeps_long_public_roots_and_self_reply_chains() -> None:
    identity = make_identity(
        identity_id=1,
        acct="mistersql",
        api_base_url="https://mastodon.social",
        account_id="301226",
    )
    long_text = "<p>" + ("word " * 130) + "</p>"
    root = make_post(
        post_id="root-1",
        author_acct="mistersql",
        author_id="301226",
        content=long_text,
        created_at=datetime(2026, 2, 11, 14, 26, 42),
    )
    short_root = make_post(
        post_id="root-2",
        author_acct="mistersql",
        author_id="301226",
        content="<p>Short root.</p>",
        created_at=datetime(2026, 2, 12, 9, 0, 0),
    )
    self_reply = make_post(
        post_id="reply-2",
        author_acct="mistersql",
        author_id="301226",
        content="<p>Follow-up thought.</p>",
        created_at=datetime(2026, 2, 12, 9, 3, 0),
        in_reply_to_id="root-2",
    )
    private_root = make_post(
        post_id="root-3",
        author_acct="mistersql",
        author_id="301226",
        content=long_text,
        created_at=datetime(2026, 2, 13, 8, 0, 0),
        visibility="direct",
    )

    payload = build_storm_exports(
        identities=[identity],
        posts=[root, short_root, self_reply, private_root],
        min_text_length=DEFAULT_MIN_TEXT_LENGTH,
    )

    assert payload["storm_count"] == 2
    assert [storm["id"] for storm in payload["storms"]] == ["root-2", "root-1"]
    assert payload["storms"][0]["reply_count"] == 1
    assert payload["storms"][0]["branches"][0]["id"] == "reply-2"
    assert payload["authors"] == [
        {
            "acct": "mistersql",
            "api_base_url": "https://mastodon.social",
            "account_id": "301226",
            "storm_count": 2,
        }
    ]


def test_build_storm_exports_ignores_replies_from_other_authors() -> None:
    own_identity = make_identity(
        identity_id=1,
        acct="runmattrun",
        api_base_url="https://mastodon.social",
        account_id="110808772955693011",
    )
    root = make_post(
        post_id="run-1",
        author_acct="runmattrun",
        author_id="110808772955693011",
        content="<p>Marathon in the AM.</p>",
        created_at=datetime(2025, 3, 16, 2, 13, 45),
    )
    own_reply = make_post(
        post_id="run-2",
        author_acct="runmattrun",
        author_id="110808772955693011",
        content="<p>Well, I did it.</p>",
        created_at=datetime(2025, 3, 16, 7, 13, 45),
        in_reply_to_id="run-1",
    )
    other_reply = make_post(
        post_id="run-3",
        author_acct="mistersql",
        author_id="301226",
        content="<p>Congrats.</p>",
        created_at=datetime(2025, 3, 16, 7, 14, 45),
        in_reply_to_id="run-1",
    )

    payload = build_storm_exports(
        identities=[own_identity],
        posts=[root, own_reply, other_reply],
        min_text_length=DEFAULT_MIN_TEXT_LENGTH,
    )

    assert payload["storm_count"] == 1
    assert payload["storms"][0]["branches"] == [
        {
            "id": "run-2",
            "created_at": "2025-03-16T07:13:45",
            "content_html": "<p>Well, I did it.</p>",
            "content_text": "Well, I did it.",
            "cleaned_length": 15,
            "excerpt": "Well, I did it.",
            "media": [],
            "original_url": "https://mastodon.social/@runmattrun/run-2",
            "children": [],
        }
    ]
