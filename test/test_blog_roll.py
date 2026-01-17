# tests/test_blog_roll.py
import pytest
from datetime import datetime, timedelta
from mastodon_is_my_blog.store import CachedAccount, CachedPost

# Helper to create accounts quickly
async def create_account(session, id, name, following=False, followed_by=False, note="", active_days_ago=0,display_name=""):
    if not display_name:
        display_name= name.title()
    last_status = datetime.utcnow() - timedelta(days=active_days_ago)
    acc = CachedAccount(
        id=id,
        acct=name,
        display_name=display_name,
        avatar="http://fake.url",
        url="http://fake.url",
        is_following=following,
        is_followed_by=followed_by,
        note=note,
        last_status_at=last_status
    )
    session.add(acc)
    return acc

# Helper to create posts (for chatty/broadcaster stats)
async def create_posts(session, author_id, count, is_reply=False):
    for i in range(count):
        p = CachedPost(
            id=f"{author_id}_{i}_{is_reply}",
            content="test",
            created_at=datetime.utcnow(),
            visibility="public",
            author_acct="test",
            author_id=author_id,
            is_reply=is_reply,
            # Required non-nulls
            is_reblog=False,
            has_media=False, has_video=False, has_news=False,
            has_tech=False, has_link=False, has_question=False
        )
        session.add(p)

@pytest.mark.asyncio
async def test_blog_roll_filter_friends(client, db_session):
    """Test 'top_friends' only returns people I follow"""
    await create_account(db_session, "1", "friend", following=True)
    await create_account(db_session, "2", "stranger", following=False)
    await db_session.commit()

    resp = await client.get("/api/public/accounts/blogroll?filter_type=top_friends")
    assert resp.status_code == 200
    data = resp.json()

    assert len(data) == 1
    assert data[0]['id'] == "1"
    assert data[0]['acct'] == "friend"

@pytest.mark.asyncio
async def test_blog_roll_filter_mutuals(client, db_session):
    """Test 'mutuals' returns only people where following=True AND followed_by=True"""
    await create_account(db_session, "1", "mutual", following=True, followed_by=True)
    await create_account(db_session, "2", "fan", following=False, followed_by=True)
    await create_account(db_session, "3", "celebrity", following=True, followed_by=False)
    await db_session.commit()

    resp = await client.get("/api/public/accounts/blogroll?filter_type=mutuals")
    data = resp.json()

    if resp.status_code != 200:
        pytest.fail(f"API Error {resp.status_code}: {data}")

    assert len(data) == 1
    assert data[0]['acct'] == "mutual"

@pytest.mark.asyncio
async def test_blog_roll_filter_bots(client, db_session):
    """Test 'bots' heuristic based on name or note"""
    await create_account(db_session, "1", "human", note="I like toast")
    await create_account(db_session, "2", "robot_beep", note="I am an automated bot")
    await create_account(db_session, "3", "news_bot", display_name="News Bot")
    await db_session.commit()

    resp = await client.get("/api/public/accounts/blogroll?filter_type=bots")
    data = resp.json()

    ids = [d['id'] for d in data]
    assert "2" in ids
    assert "3" in ids
    assert "1" not in ids

@pytest.mark.asyncio
async def test_blog_roll_chatty_calculation(client, db_session):
    """
    Test 'chatty':
    Logic: reply_ratio > 0.5 AND total_posts >= 5
    """
    # 1. The Chatterbox: 10 posts, 8 replies (80% ratio) -> Should Pass
    await create_account(db_session, "100", "chatterbox")
    await create_posts(db_session, "100", count=2, is_reply=False)
    await create_posts(db_session, "100", count=8, is_reply=True)

    # 2. The Broadcaster: 10 posts, 1 reply (10% ratio) -> Should Fail
    await create_account(db_session, "200", "news_anchor")
    await create_posts(db_session, "200", count=9, is_reply=False)
    await create_posts(db_session, "200", count=1, is_reply=True)

    # 3. The Newbie: 2 posts, 2 replies (100% ratio) -> Should Fail (total < 5)
    await create_account(db_session, "300", "newbie")
    await create_posts(db_session, "300", count=2, is_reply=True)

    await db_session.commit()

    resp = await client.get("/api/public/accounts/blogroll?filter_type=chatty")
    data = resp.json()

    assert len(data) == 1
    assert data[0]['acct'] == "chatterbox"

@pytest.mark.asyncio
async def test_blog_roll_broadcasters_calculation(client, db_session):
    """
    Test 'broadcasters':
    Logic: reply_ratio < 0.2 AND total_posts >= 5
    """
    # 1. The Chatterbox (80%) -> Fail
    await create_account(db_session, "100", "chatterbox")
    await create_posts(db_session, "100", count=2, is_reply=False)
    await create_posts(db_session, "100", count=8, is_reply=True)

    # 2. The Broadcaster (0%) -> Pass
    await create_account(db_session, "200", "news_anchor")
    await create_posts(db_session, "200", count=10, is_reply=False)

    await db_session.commit()

    resp = await client.get("/api/public/accounts/blogroll?filter_type=broadcasters")
    data = resp.json()

    assert len(data) == 1
    assert data[0]['acct'] == "news_anchor"