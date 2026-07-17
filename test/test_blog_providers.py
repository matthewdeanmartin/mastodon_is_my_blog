from pathlib import Path

import pytest

from mastodon_is_my_blog import blog_providers
from mastodon_is_my_blog.blog_providers.eleventy import EleventyProvider
from mastodon_is_my_blog.blog_providers.fallback import FallbackProvider
from mastodon_is_my_blog.blog_providers.pelican import PelicanProvider, render_article, write_site_sources

SAMPLE_STORMS = {
    "generated_at": "2026-07-16T00:00:00+00:00",
    "storm_count": 1,
    "authors": [{"acct": "alice", "api_base_url": "https://example.social", "account_id": "42", "storm_count": 1}],
    "storms": [
        {
            "id": "111",
            "slug": "2026-07-15-birds-on-bicycles-111",
            "title": "Birds on bicycles",
            "author": {"acct": "alice", "api_base_url": "https://example.social", "account_id": "42"},
            "created_at": "2026-07-15T10:30:00+00:00",
            "content_html": "<p>Release the <b>birds</b>!</p>",
            "content_text": "Release the birds!",
            "cleaned_length": 18,
            "excerpt": "Release the birds!",
            "media": [{"type": "image", "url": "https://example.social/img.png", "preview_url": None, "description": "a bird"}],
            "original_url": "https://example.social/@alice/111",
            "reply_count": 1,
            "branches": [
                {
                    "id": "112",
                    "created_at": "2026-07-15T10:31:00+00:00",
                    "content_html": "<p>On bicycles!</p>",
                    "content_text": "On bicycles!",
                    "cleaned_length": 12,
                    "excerpt": "On bicycles!",
                    "media": [],
                    "original_url": "https://example.social/@alice/112",
                    "children": [],
                }
            ],
        }
    ],
}

SAMPLE_BLOGROLL = {
    "categories": [
        {
            "id": "top_friends",
            "title": "Top friends",
            "count": 1,
            "accounts": [
                {
                    "acct": "bob@example.social",
                    "display_name": "Bob",
                    "avatar": "",
                    "mastodon_social_url": "https://mastodon.social/@bob@example.social",
                    "note": "Rides a bicycle",
                    "last_status_at": None,
                }
            ],
        }
    ]
}


def test_resolve_provider_prefers_eleventy_then_pelican(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BLOG_BUILDER", raising=False)
    monkeypatch.setattr(EleventyProvider, "available", lambda self: True)
    assert blog_providers.resolve_provider().name == "eleventy"

    monkeypatch.setattr(EleventyProvider, "available", lambda self: False)
    assert blog_providers.resolve_provider().name == "pelican"

    monkeypatch.setattr(PelicanProvider, "available", lambda self: False)
    assert blog_providers.resolve_provider().name == "fallback"


def test_resolve_provider_honors_pin_and_falls_through_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(EleventyProvider, "available", lambda self: True)

    monkeypatch.setenv("BLOG_BUILDER", "pelican")
    assert blog_providers.resolve_provider().name == "pelican"

    monkeypatch.setenv("BLOG_BUILDER", "fallback")
    assert blog_providers.resolve_provider().name == "fallback"

    monkeypatch.setattr(PelicanProvider, "available", lambda self: False)
    monkeypatch.setenv("BLOG_BUILDER", "pelican")
    assert blog_providers.resolve_provider().name == "eleventy"

    monkeypatch.setenv("BLOG_BUILDER", "not-a-builder")
    assert blog_providers.resolve_provider().name == "eleventy"


def test_render_article_escapes_metadata_and_keeps_content_html() -> None:
    storm = dict(SAMPLE_STORMS["storms"][0], title='Quotes " & <angles>', excerpt='say "hi"')
    article = render_article(storm)
    assert "<title>Quotes &quot; &amp; &lt;angles&gt;</title>" in article
    assert 'content="say &quot;hi&quot;"' in article
    assert "<p>Release the <b>birds</b>!</p>" in article
    assert "<p>On bicycles!</p>" in article


def test_write_site_sources_lays_out_pelican_project(tmp_path: Path) -> None:
    count = write_site_sources(tmp_path, SAMPLE_STORMS, SAMPLE_BLOGROLL)
    assert count == 1
    assert (tmp_path / "pelicanconf.py").exists()
    assert (tmp_path / "content" / "2026-07-15-birds-on-bicycles-111.html").exists()
    assert (tmp_path / "content" / "pages" / "blogroll.html").exists()
    conf = (tmp_path / "pelicanconf.py").read_text(encoding="utf-8")
    assert "RELATIVE_URLS = True" in conf
    assert 'SITENAME = "alice\'s blog"' in conf


def test_pelican_provider_builds_real_site(tmp_path: Path) -> None:
    provider = PelicanProvider()
    assert provider.available(), "pelican is a project dependency and must import"

    out_dir = tmp_path / "site"
    assert provider.build(SAMPLE_STORMS, SAMPLE_BLOGROLL, out_dir) is True

    index = (out_dir / "index.html").read_text(encoding="utf-8")
    assert "Birds on bicycles" in index

    article = (out_dir / "posts" / "2026-07-15-birds-on-bicycles-111" / "index.html").read_text(encoding="utf-8")
    assert "Release the <b>birds</b>!" in article
    assert "On bicycles!" in article
    assert "https://example.social/@alice/111" in article

    blogroll_page = (out_dir / "pages" / "blogroll" / "index.html").read_text(encoding="utf-8")
    assert "Bob" in blogroll_page


def test_fallback_provider_always_builds(tmp_path: Path) -> None:
    provider = FallbackProvider()
    assert provider.available()
    out_dir = tmp_path / "site"
    assert provider.build(SAMPLE_STORMS, SAMPLE_BLOGROLL, out_dir) is True
    assert (out_dir / "index.html").exists()
