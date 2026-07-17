"""The contract every static blog builder implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BlogProvider(ABC):
    """One way of turning the storm/blogroll exports into a static site.

    Implementations are synchronous (callers run them via asyncio.to_thread)
    and must be safe to call with out_dir missing or holding a previous build.
    """

    name: str
    description: str

    @abstractmethod
    def available(self) -> bool:
        """Can this provider build right now, on this machine?"""

    @abstractmethod
    def build(self, storms: dict[str, Any], blogroll: dict[str, Any], out_dir: Path) -> bool:
        """Build the site into out_dir. Returns False on any failure so the
        caller can fall back to the next provider."""
