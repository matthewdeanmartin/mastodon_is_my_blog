"""Last-resort provider: the single-page plain-HTML renderer. Always works,
so "my blog is live" is never a 404."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mastodon_is_my_blog.blog_providers.base import BlogProvider


class FallbackProvider(BlogProvider):
    name = "fallback"
    description = "Plain single-page HTML (always available)"

    def available(self) -> bool:
        return True

    def build(self, storms: dict[str, Any], blogroll: dict[str, Any], out_dir: Path) -> bool:
        from mastodon_is_my_blog.blog_build import render_fallback_blog

        _ = blogroll
        render_fallback_blog(out_dir, storms)
        return True
