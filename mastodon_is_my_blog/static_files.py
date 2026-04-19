from __future__ import annotations

import importlib.resources
from pathlib import Path


def get_static_dir() -> Path:
    """Return a Path to the compiled Angular static files bundled with this package."""
    ref = importlib.resources.files("mastodon_is_my_blog.static") / "browser"
    return Path(str(ref))
