from __future__ import annotations

import os
from pathlib import Path

import dotenv

# Where each env key came from, recorded as keys are loaded. Values are a
# file path string; keys that were already in the shell environment are not
# recorded here (see describe_setting_source).
setting_sources: dict[str, str] = {}


def get_config_dir(create: bool = False) -> Path:
    """Per-user config directory. MIMB_CONFIG_DIR overrides (tests, containers)."""
    override = os.environ.get("MIMB_CONFIG_DIR")
    if override:
        config_dir = Path(override)
    else:
        from platformdirs import user_config_dir

        config_dir = Path(user_config_dir(appname="mastodon_is_my_blog", appauthor=False))
    if create:
        config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_data_dir(create: bool = False) -> Path:
    """Per-user data directory (the default SQLite home). MIMB_DATA_DIR
    overrides (tests, containers) — platformdirs asks the OS for the real
    profile directories, so plain HOME/LOCALAPPDATA overrides do nothing
    on Windows."""
    override = os.environ.get("MIMB_DATA_DIR")
    if override:
        data_dir = Path(override)
    else:
        from platformdirs import user_data_dir

        data_dir = Path(user_data_dir(appname="mastodon_is_my_blog", appauthor=False))
    if create:
        data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_settings_env_path(create_dir: bool = False) -> Path:
    """The persistent settings file written by `mimb init` (dotenv format).

    Lives in the per-user config dir so it applies no matter which directory
    mimb is launched from — a ./.env in the current directory and shell env
    vars still override it.
    """
    return get_config_dir(create=create_dir) / "settings.env"


def load_environment() -> None:
    """Load configuration without replacing shell overrides.

    Precedence (first hit wins): shell environment > ./.env in the current
    directory (developer/deploy override) > the per-user settings file.
    Safe to call repeatedly; already-set keys are never replaced.
    """
    for path in (Path(".env"), get_settings_env_path()):
        if not path.is_file():
            continue
        for key, value in dotenv.dotenv_values(path).items():
            if value is None or key in os.environ:
                continue
            os.environ[key] = value
            setting_sources[key] = str(path)


def describe_setting_source(key: str) -> str:
    """Human-readable answer to 'where did this setting come from?'."""
    if key in setting_sources:
        return setting_sources[key]
    if key in os.environ:
        return "shell environment"
    return "not set (built-in default)"
