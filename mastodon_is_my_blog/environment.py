from __future__ import annotations

import dotenv


def load_environment() -> None:
    """Load repository-local configuration without replacing shell overrides."""
    dotenv.load_dotenv(override=False)
