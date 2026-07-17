"""Eleventy provider: the original Node.js themed blog (docs-src).

Preferred when its node_modules are installed — it is the author's own theme.
All the actual build machinery stays in blog_build/blog_publish; this class
just adapts it to the provider contract. Imports are lazy to avoid a cycle
(blog_build resolves providers at build time).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mastodon_is_my_blog.blog_providers.base import BlogProvider


class EleventyProvider(BlogProvider):
    name = "eleventy"
    description = "Node.js themed blog (docs-src; requires npm install)"

    def available(self) -> bool:
        from mastodon_is_my_blog.blog_build import eleventy_site_dir, find_eleventy_binary

        site_dir = eleventy_site_dir()
        return find_eleventy_binary(site_dir) is not None and (site_dir / ".eleventy.js").exists()

    def build(self, storms: dict[str, Any], blogroll: dict[str, Any], out_dir: Path) -> bool:
        from mastodon_is_my_blog.blog_build import eleventy_site_dir, run_eleventy_build
        from mastodon_is_my_blog.blog_publish import ensure_generated_styles

        ensure_generated_styles(eleventy_site_dir())
        return run_eleventy_build(json.dumps(storms, indent=2), json.dumps(blogroll, indent=2), out_dir)
