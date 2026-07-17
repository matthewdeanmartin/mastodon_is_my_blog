"""Local-mode blog publishing: build the Eleventy blog into ./docs and push it.

Self-hosted users run the server from a checkout (or any git repo they want
their blog published from). The Publish button in the admin UI:

1. builds the Eleventy site into <cwd>/docs (GitHub Pages' "deploy from
   branch /docs" convention, and the same output the repo's own Makefile
   build-blog target produces),
2. optionally writes a GitHub Pages deploy workflow, and
3. commits and pushes ./docs — git is the de facto upload channel for
   static blog hosts.

Hosted mode never uses this module: tenant blogs rebuild automatically
(blog_build.py) and the endpoints 404 there.

The build itself goes through blog_providers/: Eleventy when its Node
node_modules are installed, otherwise the bundled Pelican (pure Python, ships
in the wheel), otherwise the plain-HTML fallback — publish always produces a
publishable docs/.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from mastodon_is_my_blog.blog_build import (
    BUILD_LOCK,
    eleventy_site_dir,
    find_eleventy_binary,
    render_fallback_blog,
)

logger = logging.getLogger(__name__)

GIT_TIMEOUT_SECONDS = 120
PAGES_WORKFLOW_RELPATH = Path(".github") / "workflows" / "publish-blog.yml"


def publish_repo_root() -> Path:
    """Where 'publish' lands: the server's working directory. Overridable so
    the blog repo doesn't have to be the repo the server runs from."""
    return Path(os.environ.get("PUBLISH_REPO_DIR", os.getcwd())).resolve()


def docs_output_dir() -> Path:
    return publish_repo_root() / "docs"


def run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    """Run git without ever prompting (a credential prompt would hang the
    server); returns (returncode, combined output)."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        result = subprocess.run(  # noqa: S603 - fixed binary, argv built by us
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
            env=env,
        )
    except FileNotFoundError:
        return 127, "git is not installed or not on PATH"
    except subprocess.TimeoutExpired:
        return 124, f"git {' '.join(args)} timed out after {GIT_TIMEOUT_SECONDS}s"
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


def get_publish_status() -> dict[str, Any]:
    """Everything the Publish panel needs to decide which buttons to show."""
    from mastodon_is_my_blog.blog_providers import provider_availability, resolve_provider

    root = publish_repo_root()
    site_dir = eleventy_site_dir()
    is_repo = (root / ".git").exists()

    branch = None
    remote_url = None
    docs_dirty = False
    if is_repo:
        code, out = run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
        branch = out if code == 0 else None
        code, out = run_git(["remote", "get-url", "origin"], root)
        remote_url = out if code == 0 else None
        code, out = run_git(["status", "--porcelain", "--", "docs"], root)
        docs_dirty = code == 0 and bool(out)

    return {
        "repo_root": str(root),
        "git_repo": is_repo,
        "branch": branch,
        "remote_url": remote_url,
        "node_available": shutil.which("node") is not None,
        "eleventy_available": find_eleventy_binary(site_dir) is not None,
        "eleventy_site_dir": str(site_dir),
        "builder": resolve_provider().name,
        "builders": provider_availability(),
        "docs_exists": (docs_output_dir() / "index.html").exists(),
        "docs_dirty": docs_dirty,
        "pages_workflow_exists": (root / PAGES_WORKFLOW_RELPATH).exists(),
        "pages_workflow_path": str(PAGES_WORKFLOW_RELPATH).replace(os.sep, "/"),
    }


def ensure_generated_styles(site_dir: Path) -> None:
    """The Eleventy build expects sass output under src/assets/generated
    (normally produced by `npm run build:styles`). Regenerate it when missing
    so a fresh checkout still builds a styled blog."""
    if (site_dir / "src" / "assets" / "generated" / "critical.css").exists():
        return
    npm = shutil.which("npm")
    if npm is None:
        logger.warning("generated styles missing and npm not found — blog may build unstyled")
        return
    result = subprocess.run(  # noqa: S603 - fixed binary
        [npm, "--prefix", str(site_dir), "run", "build:styles"],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        logger.warning("npm run build:styles failed: %s", result.stderr[-1000:])


async def build_docs() -> dict[str, Any]:
    """Build the local user's blog into <repo>/docs with the resolved provider
    (Eleventy > bundled Pelican > plain fallback) — publish must always
    produce something."""
    from mastodon_is_my_blog.blog_providers import resolve_provider
    from mastodon_is_my_blog.storm_export import load_blogroll_export_data, load_storm_export_data

    storms = await load_storm_export_data(meta_account_id=None)
    blogroll = await load_blogroll_export_data(meta_account_id=None)
    out_dir = docs_output_dir()

    provider = resolve_provider()
    async with BUILD_LOCK:
        built = await asyncio.to_thread(provider.build, storms, blogroll, out_dir)
        if not built:
            if out_dir.exists():
                await asyncio.to_thread(shutil.rmtree, out_dir, True)
            render_fallback_blog(out_dir, storms)

    page_count = sum(1 for _ in out_dir.rglob("index.html"))
    builder = provider.name if built else "fallback"
    logger.info("local blog built builder=%s pages=%s at %s", builder, page_count, out_dir)
    return {
        "builder": builder,
        "docs_path": str(out_dir),
        "pages": page_count,
        "storm_count": len(storms.get("storms", [])),
    }


def pages_workflow_content(branch: str) -> str:
    return f"""name: Publish blog to GitHub Pages

on:
  push:
    branches: [{branch}]
    paths:
      - "docs/**"
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{{{ steps.deployment.outputs.page_url }}}}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: docs
      - id: deployment
        uses: actions/deploy-pages@v4
"""


def create_pages_workflow(overwrite: bool = False) -> dict[str, Any]:
    root = publish_repo_root()
    workflow_path = root / PAGES_WORKFLOW_RELPATH
    if workflow_path.exists() and not overwrite:
        return {"created": False, "path": str(workflow_path), "detail": "Workflow already exists"}

    code, out = run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    branch = out if code == 0 and out else "main"
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(pages_workflow_content(branch), encoding="utf-8")
    relpath = str(PAGES_WORKFLOW_RELPATH).replace(os.sep, "/")
    return {"created": True, "path": str(workflow_path), "detail": f"Wrote {relpath} (deploys docs/ on push to {branch})"}


def git_publish(message: str) -> dict[str, Any]:
    """Stage docs/ (and the Pages workflow if present), commit, push."""
    root = publish_repo_root()
    if not (root / ".git").exists():
        return {"ok": False, "detail": f"{root} is not a git repository"}
    if not (docs_output_dir() / "index.html").exists():
        return {"ok": False, "detail": "No built blog in docs/ — build first"}

    to_stage = ["docs"]
    if (root / PAGES_WORKFLOW_RELPATH).exists():
        to_stage.append(str(PAGES_WORKFLOW_RELPATH))
    code, out = run_git(["add", "--", *to_stage], root)
    if code != 0:
        return {"ok": False, "detail": f"git add failed: {out}"}

    # Anything actually staged? Commit with nothing staged is an error we can
    # answer more helpfully ourselves.
    code, _ = run_git(["diff", "--cached", "--quiet"], root)
    if code == 0:
        return {"ok": True, "pushed": False, "detail": "Nothing to publish — docs/ is unchanged since the last commit"}

    code, out = run_git(["commit", "-m", message or "Publish blog"], root)
    if code != 0:
        return {"ok": False, "detail": f"git commit failed: {out}"}
    commit_summary = out.splitlines()[0] if out else "committed"

    code, out = run_git(["push"], root)
    if code != 0:
        return {
            "ok": False,
            "detail": f"Committed locally ({commit_summary}) but push failed: {out}. Push manually with `git push`.",
        }
    return {"ok": True, "pushed": True, "detail": f"{commit_summary} — pushed to remote"}
