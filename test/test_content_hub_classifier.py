import pytest

from mastodon_is_my_blog.content_hub_classifier import (
    classify_tab,
    is_jobs_post,
    is_videos_post,
)
from test.conftest import make_cached_post


def test_is_jobs_post_true_when_has_job_set() -> None:
    post = make_cached_post(has_job=True)
    assert is_jobs_post(post) is True


def test_is_jobs_post_false_when_has_job_not_set() -> None:
    post = make_cached_post(has_job=False)
    assert is_jobs_post(post) is False


def test_is_videos_post_uses_video_flag() -> None:
    assert is_videos_post(make_cached_post(has_video=True)) is True
    assert is_videos_post(make_cached_post(has_video=False)) is False


def test_classify_tab_combines_default_video_and_jobs_tabs() -> None:
    post = make_cached_post(has_video=True, has_job=True)
    assert classify_tab(post) == {"text", "videos", "jobs"}


def test_classify_tab_text_only() -> None:
    post = make_cached_post()
    assert classify_tab(post) == {"text"}
