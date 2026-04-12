import pytest

from mastodon_is_my_blog.content_hub_classifier import (
    classify_tab,
    is_jobs_post,
    is_videos_post,
    strip_html,
)
from test.conftest import make_cached_post


def test_strip_html_normalizes_case_and_whitespace() -> None:
    assert strip_html("<p>Hello <strong>World</strong></p>\n<div> Again </div>") == (
        "hello world again"
    )


def test_is_jobs_post_matches_job_tag_keywords() -> None:
    post = make_cached_post(content="<p>Unrelated text</p>")
    post.tags = '["fedihired", "python"]'

    assert is_jobs_post(post) is True


def test_is_jobs_post_falls_back_to_text_when_tags_are_invalid_json() -> None:
    post = make_cached_post(content="<p>We are hiring a remote engineer</p>")
    post.tags = "not-json"

    assert is_jobs_post(post) is True


def test_is_jobs_post_returns_false_without_job_signals() -> None:
    post = make_cached_post(content="<p>Shipping a new feature today</p>")
    post.tags = '["release", "update"]'

    assert is_jobs_post(post) is False


def test_is_videos_post_uses_video_flag() -> None:
    assert is_videos_post(make_cached_post(has_video=True)) is True
    assert is_videos_post(make_cached_post(has_video=False)) is False


def test_classify_tab_combines_default_video_and_jobs_tabs() -> None:
    post = make_cached_post(
        content="<p>Now hiring for a video editor</p>",
        has_video=True,
    )

    assert classify_tab(post) == {"text", "videos", "jobs"}
