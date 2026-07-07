"""Per-tenant static blog builds (blog_build.py, server_side.md Phase 2)."""

import json
import subprocess
from pathlib import Path

import pytest

from mastodon_is_my_blog import blog_build

STORMS = {
    "storms": [
        {
            "id": "s1",
            "title": "On <gardens>",
            "created_at": "2026-01-02",
            "author": {"acct": "ada@mock.local"},
            "posts": [{"content": "<p>first toot</p>"}, {"content": "<p>second toot</p>"}],
        }
    ]
}


def test_fallback_renderer_writes_readable_index(tmp_path):
    out = tmp_path / "tenant_1"
    blog_build.render_fallback_blog(out, STORMS)
    html_text = (out / "index.html").read_text(encoding="utf-8")
    assert "On &lt;gardens&gt;" in html_text  # title escaped
    assert "<p>first toot</p>" in html_text  # content is already-sanitized HTML
    assert "ada@mock.local" in html_text


def test_fallback_renderer_empty_state(tmp_path):
    out = tmp_path / "tenant_2"
    blog_build.render_fallback_blog(out, {"storms": []})
    assert "No posts synced yet" in (out / "index.html").read_text(encoding="utf-8")


def fake_site_dir(tmp_path: Path) -> Path:
    """A minimal Eleventy project shape: config, binary, checked-in _data."""
    site = tmp_path / "docs-src"
    (site / "src" / "_data").mkdir(parents=True)
    (site / "node_modules" / ".bin").mkdir(parents=True)
    (site / ".eleventy.js").write_text("// config", encoding="utf-8")
    (site / "node_modules" / ".bin" / "eleventy.cmd").write_text("", encoding="utf-8")
    (site / "src" / "_data" / "storms.json").write_text('{"storms": ["OWNER DATA"]}', encoding="utf-8")
    (site / "src" / "_data" / "blogroll.json").write_text('{"accounts": ["OWNER DATA"]}', encoding="utf-8")
    return site


def test_eleventy_build_swaps_data_in_and_restores(tmp_path, monkeypatch):
    site = fake_site_dir(tmp_path)
    monkeypatch.setenv("ELEVENTY_SITE_DIR", str(site))

    seen = {}

    def fake_run(argv, **kwargs):
        # Capture what the build would have read: tenant data must be in place.
        seen["storms"] = (site / "src" / "_data" / "storms.json").read_text(encoding="utf-8")
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(blog_build.subprocess, "run", fake_run)

    ok = blog_build.run_eleventy_build('{"storms": ["TENANT DATA"]}', "{}", tmp_path / "out")
    assert ok is True
    assert seen["storms"] == '{"storms": ["TENANT DATA"]}'
    assert f"--output={(tmp_path / 'out').resolve()}" in seen["argv"]
    # The site owner's own checked-in data is back afterwards.
    assert "OWNER DATA" in (site / "src" / "_data" / "storms.json").read_text(encoding="utf-8")
    assert "OWNER DATA" in (site / "src" / "_data" / "blogroll.json").read_text(encoding="utf-8")


def test_eleventy_build_restores_data_even_on_failure(tmp_path, monkeypatch):
    site = fake_site_dir(tmp_path)
    monkeypatch.setenv("ELEVENTY_SITE_DIR", str(site))
    monkeypatch.setattr(
        blog_build.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom"),
    )

    ok = blog_build.run_eleventy_build("{}", "{}", tmp_path / "out")
    assert ok is False
    assert "OWNER DATA" in (site / "src" / "_data" / "storms.json").read_text(encoding="utf-8")


def test_no_eleventy_means_not_built(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENTY_SITE_DIR", str(tmp_path / "nowhere"))
    assert blog_build.run_eleventy_build("{}", "{}", tmp_path / "out") is False


@pytest.mark.asyncio
async def test_build_tenant_blog_falls_back_without_eleventy(
    tmp_path, monkeypatch, patch_async_session
):
    from mastodon_is_my_blog import storm_export

    patch_async_session(storm_export)
    monkeypatch.setenv("ELEVENTY_SITE_DIR", str(tmp_path / "nowhere"))
    monkeypatch.setenv("BLOG_DIR", str(tmp_path / "blogs"))

    result = await blog_build.build_tenant_blog(9, 999)

    assert result["builder"] == "fallback"
    index = Path(result["blog_path"]) / "index.html"
    assert index.exists()
    assert "No posts synced yet" in index.read_text(encoding="utf-8")


def test_blog_json_payload_roundtrip(tmp_path):
    # The builder receives serialized payloads; make sure our test fixture is
    # actually valid JSON for it (guards fixture rot).
    json.dumps(STORMS)
