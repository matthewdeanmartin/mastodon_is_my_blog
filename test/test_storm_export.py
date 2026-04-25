from datetime import datetime

from mastodon_is_my_blog.store import (
    CachedAccount,
    CachedNotification,
    CachedPost,
    MastodonIdentity,
)
from mastodon_is_my_blog.storm_export import (
    DEFAULT_MIN_TEXT_LENGTH,
    build_blogroll_export,
    build_storm_exports,
    clean_mastodon_text,
)


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
        has_book=False,
        media_attachments=media_attachments,
        tags=None,
        replies_count=0,
        reblogs_count=0,
        favourites_count=0,
    )


def make_account(
    *,
    account_id: str,
    acct: str,
    display_name: str,
    mastodon_identity_id: int = 1,
    avatar: str = "https://img.example.com/avatar.png",
    note: str = "",
    bot: bool = False,
    is_following: bool = True,
    is_followed_by: bool = False,
    last_status_at: datetime | None = None,
) -> CachedAccount:
    return CachedAccount(
        id=account_id,
        meta_account_id=1,
        mastodon_identity_id=mastodon_identity_id,
        acct=acct,
        display_name=display_name,
        avatar=avatar,
        url=f"https://example.com/@{acct}",
        note=note,
        bot=bot,
        locked=False,
        created_at=None,
        header="",
        fields="[]",
        followers_count=0,
        following_count=0,
        statuses_count=0,
        is_following=is_following,
        is_followed_by=is_followed_by,
        last_status_at=last_status_at,
        cached_post_count=0,
        cached_reply_count=0,
    )


def make_notification(
    *,
    notification_id: str,
    identity_id: int,
    account_id: str,
    account_acct: str,
    notification_type: str = "mention",
    created_at: datetime,
) -> CachedNotification:
    return CachedNotification(
        id=notification_id,
        meta_account_id=1,
        identity_id=identity_id,
        type=notification_type,
        created_at=created_at,
        account_id=account_id,
        account_acct=account_acct,
        status_id=None,
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


def test_build_blogroll_export_groups_top_friends_mutuals_and_bots() -> None:
    accounts = [
        make_account(
            account_id="friend-1",
            acct="friend@example.com",
            display_name="Friend",
            is_followed_by=True,
            last_status_at=datetime(2026, 4, 10, 12, 0, 0),
            note="<p>Writes about software.</p>",
        ),
        make_account(
            account_id="mutual-1",
            acct="mutual@example.com",
            display_name="Mutual",
            is_followed_by=True,
            last_status_at=datetime(2026, 4, 9, 8, 0, 0),
        ),
        make_account(
            account_id="bot-1",
            acct="helperbot@example.com",
            display_name="Helper Bot",
            bot=True,
            last_status_at=datetime(2026, 4, 8, 8, 0, 0),
        ),
        make_account(
            account_id="following-1",
            acct="following@example.com",
            display_name="Following Only",
            last_status_at=datetime(2026, 4, 7, 8, 0, 0),
        ),
    ]
    notifications = [
        make_notification(
            notification_id="notif-1",
            identity_id=1,
            account_id="friend-1",
            account_acct="friend@example.com",
            created_at=datetime(2026, 4, 10, 12, 5, 0),
        )
    ]

    payload = build_blogroll_export(accounts=accounts, notifications=notifications)

    assert payload["warning"] == (
        "This is anonymous access so I don't know your base Mastodon instance; "
        "all links go to mastodon.social."
    )
    assert [category["id"] for category in payload["categories"]] == [
        "top_friends",
        "mutuals",
        "bots",
    ]
    assert payload["categories"][0]["accounts"] == [
        {
            "acct": "friend@example.com",
            "display_name": "Friend",
            "avatar": "https://img.example.com/avatar.png",
            "mastodon_social_url": "https://mastodon.social/@friend@example.com",
            "note": "Writes about software.",
            "last_status_at": "2026-04-10T12:00:00",
        }
    ]
    assert payload["categories"][1]["accounts"] == [
        {
            "acct": "mutual@example.com",
            "display_name": "Mutual",
            "avatar": "https://img.example.com/avatar.png",
            "mastodon_social_url": "https://mastodon.social/@mutual@example.com",
            "note": "",
            "last_status_at": "2026-04-09T08:00:00",
        }
    ]
    assert payload["categories"][2]["accounts"] == [
        {
            "acct": "helperbot@example.com",
            "display_name": "Helper Bot",
            "avatar": "https://img.example.com/avatar.png",
            "mastodon_social_url": "https://mastodon.social/@helperbot@example.com",
            "note": "",
            "last_status_at": "2026-04-08T08:00:00",
        }
    ]
