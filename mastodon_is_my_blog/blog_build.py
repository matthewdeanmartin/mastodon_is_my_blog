"""Per-tenant static blog builds (server_side.md Phase 2, first honest slice).

The Eleventy site in docs-src/ already turns storms.json + blogroll.json into
the themed static blog (it's how the author publishes their own). Hosted mode
reuses it verbatim: write the tenant's payloads into the site's _data dir,
run the local Eleventy binary with --output pointed at BLOG_DIR/tenant_{id},
restore the originals. The site emits relative URLs (relativeUrl filter), so
it serves fine from the /blogs/tenant_{id}/ subpath.

Builds are serialized with a lock — Eleventy reads shared _data state, and at
current scale a queue of one is correct, not a bottleneck. If node/Eleventy
isn't available (bare deploy, CI), a plain-HTML fallback renders instead so
"my blog is live" is never a 404.

Object storage, per-tenant subdomains, and custom domains stay later-phase;
the contract that survives them: build_tenant_blog(tenant_id, meta_account_id)
-> {"blog_path": ..., "builder": "eleventy" | "fallback"}.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BUILD_LOCK = asyncio.Lock()
ELEVENTY_TIMEOUT_SECONDS = 300


def blog_output_root() -> Path:
    return Path(os.environ.get("BLOG_DIR", "blogs"))


def eleventy_site_dir() -> Path:
    """The Eleventy project (docs-src in this repo by default). Overridable so
    a deployed image can bake it somewhere else."""
    default = Path(__file__).resolve().parent.parent / "docs-src"
    return Path(os.environ.get("ELEVENTY_SITE_DIR", str(default)))


def find_eleventy_binary(site_dir: Path) -> Path | None:
    """The site's own node_modules binary — no npx resolution surprises."""
    bin_dir = site_dir / "node_modules" / ".bin"
    for name in ("eleventy.cmd", "eleventy"):
        candidate = bin_dir / name
        if candidate.exists():
            return candidate
    return None


def run_eleventy_build(storms_json: str, blogroll_json: str, out_dir: Path) -> bool:
    """Synchronous half (runs in a thread): swap the payloads in, build, swap
    back. Returns False when Eleventy isn't runnable or the build fails —
    caller falls back to the plain renderer.
    """
    site_dir = eleventy_site_dir()
    binary = find_eleventy_binary(site_dir)
    if binary is None or not (site_dir / ".eleventy.js").exists():
        logger.info("eleventy not available under %s — using fallback renderer", site_dir)
        return False

    data_dir = site_dir / "src" / "_data"
    storms_path = data_dir / "storms.json"
    blogroll_path = data_dir / "blogroll.json"
    # The _data payloads are the site owner's own export (checked in) — always
    # put them back, even on a failed build.
    originals = {
        path: path.read_text(encoding="utf-8") if path.exists() else None
        for path in (storms_path, blogroll_path)
    }
    try:
        storms_path.write_text(storms_json, encoding="utf-8")
        blogroll_path.write_text(blogroll_json, encoding="utf-8")
        result = subprocess.run(  # noqa: S603 - fixed binary, no user input in argv
            [str(binary), f"--output={out_dir.resolve()}"],
            cwd=site_dir,
            capture_output=True,
            text=True,
            timeout=ELEVENTY_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode != 0:
            logger.error("eleventy build failed (%s): %s", result.returncode, result.stderr[-2000:])
            return False
        return True
    except (OSError, subprocess.TimeoutExpired):
        logger.exception("eleventy build errored")
        return False
    finally:
        for path, content in originals.items():
            if content is not None:
                path.write_text(content, encoding="utf-8")
            elif path.exists():
                path.unlink()


def render_fallback_blog(out_dir: Path, storms: dict[str, Any]) -> None:
    """No-node fallback: one readable index.html from the storm payload, so
    the blog URL always resolves to the tenant's actual content."""
    out_dir.mkdir(parents=True, exist_ok=True)
    articles = []
    for storm in storms.get("storms", []):
        author = (storm.get("author") or {}).get("acct", "")
        title = storm.get("title") or "(untitled storm)"
        body = "\n".join(post.get("content", "") for post in storm.get("posts", []))
        articles.append(
            f"<article><h2>{html.escape(str(title))}</h2>"
            f'<p class="meta">{html.escape(str(author))} · {html.escape(str(storm.get("created_at", "")))}</p>'
            f"{body}</article>"
        )
    body_html = "\n".join(articles) or "<p>No posts synced yet — connect a Mastodon account and sync.</p>"
    (out_dir / "index.html").write_text(
        f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<title>My blog</title>
<style>body{{font-family:Georgia,serif;max-width:680px;margin:3rem auto;line-height:1.6;padding:0 1rem}}
.meta{{color:#666;font-size:0.9rem}}article{{border-top:1px solid #ddd;padding-top:1rem;margin-top:1rem}}</style>
</head>
<body>
<h1>My blog</h1>
{body_html}
</body>
</html>
""",
        encoding="utf-8",
    )


async def build_tenant_blog(tenant_id: int, meta_account_id: int) -> dict:
    """Build (or rebuild) the tenant's static blog under BLOG_DIR/tenant_{id}.
    Serves at /blogs/tenant_{id}/ (main.py mounts BLOG_DIR in server mode).
    """
    import json

    from mastodon_is_my_blog.storm_export import load_blogroll_export_data, load_storm_export_data

    storms = await load_storm_export_data(meta_account_id=meta_account_id)
    blogroll = await load_blogroll_export_data(meta_account_id=meta_account_id)
    out_dir = blog_output_root() / f"tenant_{tenant_id}"

    async with BUILD_LOCK:
        built = await asyncio.to_thread(
            run_eleventy_build, json.dumps(storms, indent=2), json.dumps(blogroll, indent=2), out_dir
        )
        if not built:
            # A failed Eleventy run may have left partial output — replace it.
            if out_dir.exists():
                await asyncio.to_thread(shutil.rmtree, out_dir, True)
            render_fallback_blog(out_dir, storms)

    builder = "eleventy" if built else "fallback"
    logger.info("blog built tenant_id=%s builder=%s at %s", tenant_id, builder, out_dir)
    return {"blog_path": str(out_dir), "builder": builder}
