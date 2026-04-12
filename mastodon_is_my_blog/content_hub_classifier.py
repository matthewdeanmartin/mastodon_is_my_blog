# mastodon_is_my_blog/content_hub_classifier.py
"""
Reusable classification helpers for Content Hub tabs.

Tab membership:
- text:   all posts (default full feed)
- videos: posts with video signals
- jobs:   posts matching job-related vocabulary
"""
from __future__ import annotations

import json
import re

from mastodon_is_my_blog.store import CachedPost

# ---------------------------------------------------------------------------
# Jobs classification
# ---------------------------------------------------------------------------

JOBS_KEYWORDS: frozenset[str] = frozenset(
    [
        "hiring",
        "job",
        "jobs",
        "job opening",
        "opening",
        "role",
        "position",
        "apply",
        "contract",
        "freelance",
        "recruiter",
        "looking for",
        "we're hiring",
        "we are hiring",
        "join our team",
        "job listing",
        "job post",
        "opportunity",
        "now hiring",
        "remote",
        "full-time",
        "part-time",
    ]
)

TAG_JOBS_KEYWORDS: frozenset[str] = frozenset(
    [
        "hiring",
        "job",
        "jobs",
        "jobhunting",
        "jobsearch",
        "getfedihired",
        "fedihired",
        "career",
        "careers",
        "recruitment",
        "recruiter",
    ]
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def strip_html(html: str) -> str:
    text = _HTML_TAG_RE.sub(" ", html)
    return _WHITESPACE_RE.sub(" ", text).strip().lower()


def is_jobs_post(post: CachedPost) -> bool:
    """Return True if the post is likely a job posting."""
    text = strip_html(post.content)

    # Check tags first (cheaper)
    tags: list[str] = []
    if post.tags:
        try:
            tags = [t.lower() for t in json.loads(post.tags)]
        except (json.JSONDecodeError, TypeError):
            pass

    if any(tag in TAG_JOBS_KEYWORDS for tag in tags):
        return True

    # Check normalized text for keyword phrases
    for kw in JOBS_KEYWORDS:
        if kw in text:
            return True

    return False


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
