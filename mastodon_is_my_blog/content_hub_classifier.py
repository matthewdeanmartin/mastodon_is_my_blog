# mastodon_is_my_blog/content_hub_classifier.py
"""
Reusable classification helpers for Content Hub tabs.

Tab membership:
- text:   all posts (default full feed)
- videos: posts with video signals
- jobs:   posts with has_job flag set at ingest time
"""

from __future__ import annotations

from mastodon_is_my_blog.store import CachedPost


def is_jobs_post(post: CachedPost) -> bool:
    """Return True if the post is likely a job posting."""
    return bool(post.has_job)


def is_videos_post(post: CachedPost) -> bool:
    """Return True if the post has video content."""
    return bool(post.has_video)


def classify_tab(post: CachedPost) -> set[str]:
    """
    Return the set of Content Hub tabs this post belongs to.
    'text' is always included (default full feed).
    """
    tabs: set[str] = {"text"}
    if is_videos_post(post):
        tabs.add("videos")
    if is_jobs_post(post):
        tabs.add("jobs")
    return tabs
