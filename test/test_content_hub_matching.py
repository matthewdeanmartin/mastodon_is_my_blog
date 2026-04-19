from datetime import datetime
from test.conftest import make_cached_post, make_identity, make_meta_account

import pytest
from sqlalchemy import select

from mastodon_is_my_blog.content_hub_matching import (
    normalize_hashtag,
    normalize_search_term,
    normalize_term,
    record_search_matches,
    retro_match_group_hashtag_terms,
    retro_match_hashtag_term,
)
from mastodon_is_my_blog.store import (
    CachedPost,
    ContentHubGroup,
    ContentHubGroupTerm,
    ContentHubPostMatch,
)


def make_group(
    group_id: int = 1,
    *,
    meta_account_id: int = 1,
    identity_id: int = 1,
    name: str = "Python",
    slug: str = "python",
    source_type: str = "client_bundle",
) -> ContentHubGroup:
    now = datetime(2024, 1, 1)
    return ContentHubGroup(
        id=group_id,
        meta_account_id=meta_account_id,
        identity_id=identity_id,
        name=name,
        slug=slug,
        source_type=source_type,
        is_read_only=False,
        created_at=now,
        updated_at=now,
    )


def make_term(
    term_id: int = 1,
    *,
    group_id: int = 1,
    term: str = "python",
    term_type: str = "hashtag",
    normalized_term: str = "python",
) -> ContentHubGroupTerm:
    return ContentHubGroupTerm(
        id=term_id,
        group_id=group_id,
        term=term,
        term_type=term_type,
        normalized_term=normalized_term,
        created_at=datetime(2024, 1, 1),
    )


def test_normalize_helpers_trim_and_lowercase_terms() -> None:
    assert normalize_hashtag(" ##PyThOn ") == "##python"
    assert normalize_search_term("  From:Me  ") == "from:me"
    assert normalize_term("#Go", "hashtag") == "go"
    assert normalize_term("  Has:media ", "search") == "has:media"


@pytest.mark.asyncio
async def test_retro_match_hashtag_term_inserts_only_new_matching_posts(
    db_session,
) -> None:
    group = make_group()
    term = make_term()
    new_post = make_cached_post(post_id="match-new", content="new match")
    new_post.tags = '["python", "news"]'
    existing_post = make_cached_post(post_id="match-existing", content="existing match")
    existing_post.tags = '["python"]'
    no_match_post = make_cached_post(post_id="no-match", content="no match")
    no_match_post.tags = '["rust"]'
    bad_tags_post = make_cached_post(post_id="bad-tags", content="bad tags")
    bad_tags_post.tags = "not-json"
    db_session.add_all(
        [
            make_meta_account(),
            make_identity(),
            group,
            term,
            new_post,
            existing_post,
            no_match_post,
            bad_tags_post,
        ]
    )
    db_session.add(
        ContentHubPostMatch(
            group_id=group.id,
            post_id="match-existing",
            meta_account_id=1,
            fetched_by_identity_id=1,
            matched_term_id=term.id,
            matched_via="hashtag",
            created_at=datetime(2024, 1, 1),
        )
    )
    await db_session.commit()

    inserted = await retro_match_hashtag_term(db_session, 1, 1, group.id, term)
    await db_session.commit()

    matches = (
        (
            await db_session.execute(
                select(ContentHubPostMatch).order_by(ContentHubPostMatch.post_id)
            )
        )
        .scalars()
        .all()
    )
    cached_posts = (
        (await db_session.execute(select(CachedPost).order_by(CachedPost.id)))
        .scalars()
        .all()
    )

    assert inserted == 1
    assert [post.id for post in cached_posts] == [
        "bad-tags",
        "match-existing",
        "match-new",
        "no-match",
    ]
    assert [(match.post_id, match.matched_via) for match in matches] == [
        ("match-existing", "hashtag"),
        ("match-new", "hashtag"),
    ]


@pytest.mark.asyncio
async def test_retro_match_group_hashtag_terms_ignores_search_terms(db_session) -> None:
    group = make_group()
    hashtag_term = make_term(term_id=1, term="#Python", normalized_term="python")
    search_term = make_term(
        term_id=2,
        term="python jobs",
        term_type="search",
        normalized_term="python jobs",
    )
    matching_post = make_cached_post(post_id="match-1", content="match")
    matching_post.tags = '["python"]'

    db_session.add_all(
        [
            make_meta_account(),
            make_identity(),
            group,
            hashtag_term,
            search_term,
            matching_post,
        ]
    )
    await db_session.commit()

    inserted = await retro_match_group_hashtag_terms(
        db_session, 1, 1, group.id, [hashtag_term, search_term]
    )
    await db_session.commit()

    matches = (await db_session.execute(select(ContentHubPostMatch))).scalars().all()

    assert inserted == 1
    assert len(matches) == 1
    assert matches[0].matched_term_id == hashtag_term.id


@pytest.mark.asyncio
async def test_record_search_matches_returns_zero_for_empty_input(db_session) -> None:
    db_session.add_all(
        [make_meta_account(), make_identity(), make_group(), make_term()]
    )
    await db_session.commit()

    assert await record_search_matches(db_session, 1, 1, 1, make_term(), []) == 0


@pytest.mark.asyncio
async def test_record_search_matches_persists_rows_for_search_results(
    db_session,
) -> None:
    group = make_group()
    term = make_term(term_id=10, term="python jobs", term_type="search")
    db_session.add_all([make_meta_account(), make_identity(), group, term])
    await db_session.commit()

    inserted = await record_search_matches(
        db_session,
        1,
        1,
        group.id,
        term,
        ["post-1", "post-2"],
    )
    await db_session.commit()

    matches = (
        (
            await db_session.execute(
                select(ContentHubPostMatch).order_by(ContentHubPostMatch.post_id)
            )
        )
        .scalars()
        .all()
    )

    assert inserted == 2
    assert [
        (match.post_id, match.matched_via, match.matched_term_id) for match in matches
    ] == [
        ("post-1", "search", term.id),
        ("post-2", "search", term.id),
    ]
