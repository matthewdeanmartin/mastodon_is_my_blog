"""Pelican provider: a pure-Python static blog that ships inside the wheel.

No Node, no node_modules — pelican is a normal dependency, so a pipx install
can build a real themed blog out of the box. Each storm becomes a Pelican
HTML article (Pelican's HTMLReader takes metadata from <head> meta tags and
content from <body>, which suits Mastodon's already-HTML post content), the
blog roll becomes a page, and `python -m pelican` runs in a subprocess with
this interpreter — the same venv pelican is installed in.
"""

from __future__ import annotations

import html
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from mastodon_is_my_blog.blog_providers.base import BlogProvider

logger = logging.getLogger(__name__)

PELICAN_TIMEOUT_SECONDS = 300


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def render_media(media: list[dict[str, Any]]) -> str:
    parts = []
    for attachment in media or []:
        url = attachment.get("url") or attachment.get("preview_url")
        if not url:
            continue
        if attachment.get("type") == "image":
            parts.append(f'<p><img src="{esc(url)}" alt="{esc(attachment.get("description"))}" loading="lazy" /></p>')
        else:
            parts.append(f'<p><a href="{esc(url)}">attachment ({esc(attachment.get("type"))})</a></p>')
    return "\n".join(parts)


def render_branch(branch: dict[str, Any]) -> str:
    children = "\n".join(render_branch(child) for child in branch.get("children", []))
    return f'<div class="storm-post">\n{branch.get("content_html", "")}\n{render_media(branch.get("media", []))}\n{children}\n</div>'


def render_article(storm: dict[str, Any]) -> str:
    """One storm -> one Pelican HTML content file."""
    author = (storm.get("author") or {}).get("acct", "")
    branches = "\n".join(render_branch(branch) for branch in storm.get("branches", []))
    original_url = storm.get("original_url", "")
    footer = f'<p class="storm-origin"><a href="{esc(original_url)}">View the original thread on Mastodon</a></p>' if original_url else ""
    return f"""<html>
<head>
<title>{esc(storm.get("title") or "(untitled)")}</title>
<meta name="date" content="{esc(storm.get("created_at"))}" />
<meta name="slug" content="{esc(storm.get("slug") or storm.get("id"))}" />
<meta name="authors" content="{esc(author) or "unknown"}" />
<meta name="summary" content="{esc(storm.get("excerpt"))}" />
</head>
<body>
<div class="storm-post">
{storm.get("content_html", "")}
{render_media(storm.get("media", []))}
</div>
{branches}
{footer}
</body>
</html>
"""


def render_blogroll_page(blogroll: dict[str, Any]) -> str | None:
    categories = [category for category in blogroll.get("categories", []) if category.get("accounts")]
    if not categories:
        return None
    sections = []
    for category in categories:
        entries = []
        for account in category["accounts"]:
            note = f' — <span class="note">{esc(account.get("note"))}</span>' if account.get("note") else ""
            entries.append(f'<li><a href="{esc(account.get("mastodon_social_url"))}">{esc(account.get("display_name"))}</a> ({esc(account.get("acct"))}){note}</li>')
        sections.append(f"<h2>{esc(category.get('title'))}</h2>\n<ul>\n" + "\n".join(entries) + "\n</ul>")
    body = "\n".join(sections)
    return f"""<html>
<head>
<title>Blog roll</title>
<meta name="slug" content="blogroll" />
</head>
<body>
{body}
</body>
</html>
"""


def pelican_settings(storms: dict[str, Any]) -> str:
    authors = storms.get("authors") or []
    site_author = authors[0]["acct"] if authors else "me"
    site_name = f"{site_author}'s blog" if authors else "My blog"
    return f"""AUTHOR = {site_author!r}
SITENAME = {site_name!r}
SITEURL = ""
PATH = "content"
TIMEZONE = "UTC"
DEFAULT_LANG = "en"
DEFAULT_PAGINATION = 10

# Served from subpaths (/blogs/tenant_N/, GitHub Pages /docs) — never assume /.
RELATIVE_URLS = True
DELETE_OUTPUT_DIRECTORY = True

ARTICLE_URL = "posts/{{slug}}/"
ARTICLE_SAVE_AS = "posts/{{slug}}/index.html"
PAGE_URL = "pages/{{slug}}/"
PAGE_SAVE_AS = "pages/{{slug}}/index.html"

# Feeds need an absolute SITEURL; skip them rather than emit broken ones.
FEED_ALL_ATOM = None
CATEGORY_FEED_ATOM = None
TRANSLATION_FEED_ATOM = None
AUTHOR_FEED_ATOM = None
AUTHOR_FEED_RSS = None
"""


def write_site_sources(workdir: Path, storms: dict[str, Any], blogroll: dict[str, Any]) -> int:
    """Lay out pelicanconf.py + content/ in workdir; returns the article count."""
    content_dir = workdir / "content"
    pages_dir = content_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    (workdir / "pelicanconf.py").write_text(pelican_settings(storms), encoding="utf-8")

    count = 0
    for storm in storms.get("storms", []):
        slug = str(storm.get("slug") or storm.get("id") or count)
        (content_dir / f"{slug}.html").write_text(render_article(storm), encoding="utf-8")
        count += 1

    blogroll_page = render_blogroll_page(blogroll)
    if blogroll_page is not None:
        (pages_dir / "blogroll.html").write_text(blogroll_page, encoding="utf-8")
    return count


class PelicanProvider(BlogProvider):
    name = "pelican"
    description = "Bundled Python static site generator (no Node.js needed)"

    def available(self) -> bool:
        try:
            import pelican  # noqa: F401, PLC0415 - availability probe
        except ImportError:
            return False
        return True

    def build(self, storms: dict[str, Any], blogroll: dict[str, Any], out_dir: Path) -> bool:
        workdir = Path(tempfile.mkdtemp(prefix="mimb_pelican_"))
        try:
            write_site_sources(workdir, storms, blogroll)
            result = subprocess.run(  # noqa: S603 - our interpreter, our generated site dir
                [sys.executable, "-m", "pelican", str(workdir / "content"), "-s", str(workdir / "pelicanconf.py"), "-o", str(out_dir.resolve())],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=PELICAN_TIMEOUT_SECONDS,
                check=False,
            )
            if result.returncode != 0:
                logger.error("pelican build failed (%s): %s", result.returncode, (result.stderr or result.stdout)[-2000:])
                return False
            return (out_dir / "index.html").exists()
        except (OSError, subprocess.TimeoutExpired):
            logger.exception("pelican build errored")
            return False
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
