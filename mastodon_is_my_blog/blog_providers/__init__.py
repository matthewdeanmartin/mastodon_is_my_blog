"""Static blog builders behind one interface.

Resolution order: the BLOG_BUILDER env var pins a provider by name (eleventy |
pelican | fallback); otherwise the first available provider wins — Eleventy
(the author's themed Node site, when its node_modules are installed), then
Pelican (bundled Python dependency, the pipx-install default), then the plain
single-page fallback, which always works.
"""

from __future__ import annotations

import logging
import os

from mastodon_is_my_blog.blog_providers.base import BlogProvider
from mastodon_is_my_blog.blog_providers.eleventy import EleventyProvider
from mastodon_is_my_blog.blog_providers.fallback import FallbackProvider
from mastodon_is_my_blog.blog_providers.pelican import PelicanProvider

logger = logging.getLogger(__name__)

PROVIDERS: tuple[BlogProvider, ...] = (EleventyProvider(), PelicanProvider(), FallbackProvider())


def get_provider(name: str) -> BlogProvider | None:
    for provider in PROVIDERS:
        if provider.name == name:
            return provider
    return None


def resolve_provider() -> BlogProvider:
    """The provider a build would use right now."""
    pinned_name = os.environ.get("BLOG_BUILDER", "").strip().lower()
    if pinned_name:
        pinned = get_provider(pinned_name)
        if pinned is None:
            logger.warning("BLOG_BUILDER=%r is not a known provider (%s) — ignoring", pinned_name, ", ".join(p.name for p in PROVIDERS))
        elif not pinned.available():
            logger.warning("BLOG_BUILDER=%s is pinned but not available — falling through", pinned_name)
        else:
            return pinned
    for provider in PROVIDERS:
        if provider.available():
            return provider
    return PROVIDERS[-1]


def provider_availability() -> list[dict[str, str | bool]]:
    """For status endpoints / doctor: every provider and whether it can run."""
    return [{"name": provider.name, "description": provider.description, "available": provider.available()} for provider in PROVIDERS]
