"""Day-0 smoke tests: every top-level command run the way a brand-new user
runs it — fresh machine, no env vars, no keyring, no .env, empty home.

Each test launches a real subprocess with a scrubbed environment and temp
home/config/data directories, so import-time behavior (engine construction,
dotenv loading) is exercised exactly as on a fresh `pipx install`. Nothing
here ever touches the developer's real database, config, or keyring.

Regression net for the "shipped to PyPI, then blew up on a clean laptop"
class of bug (sprint/epic_quality_sprint01.md).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TIMEOUT_SECONDS = 240

# Every env var mimb reads anywhere; a fresh machine has none of these.
SCRUBBED_KEYS = {
    "DB_URL",
    "DB_BACKEND",
    "FRONTEND_URL",
    "ALLOWED_ORIGINS",
    "TOKEN_ENCRYPTION_KEY",
    "SESSION_SIGNING_KEY",
    "ACCOUNT_PORTAL_URL",
    "PUBLISH_REPO_DIR",
    "EXPORT_DIR",
    "HANDOFF_SHARED_SECRET",
    "LANGUAGETOOL_URL",
    "BLOG_BUILDER",
    "BLOG_DIR",
    "ELEVENTY_SITE_DIR",
}
SCRUBBED_PREFIXES = ("MASTODON_", "APP_", "MIMB_")


def day_zero_env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    for key in list(env):
        if key in SCRUBBED_KEYS or key.startswith(SCRUBBED_PREFIXES):
            env.pop(key)

    home = tmp_path / "home"
    for sub in ("AppData/Local", "AppData/Roaming", ".config", ".local/share"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["LOCALAPPDATA"] = str(home / "AppData" / "Local")
    env["APPDATA"] = str(home / "AppData" / "Roaming")
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    # The real isolation: platformdirs asks the OS for profile directories
    # (HOME/LOCALAPPDATA overrides do NOT work on Windows), so mimb honors
    # these explicit overrides everywhere it touches disk.
    env["MIMB_CONFIG_DIR"] = str(tmp_path / "config")
    env["MIMB_DATA_DIR"] = str(tmp_path / "data")
    # A machine with no usable keyring (headless Linux, locked keychain).
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_day_zero(
    args: list[str],
    tmp_path: Path,
    *,
    stdin_text: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cwd = tmp_path / "cwd"
    cwd.mkdir(exist_ok=True)
    env = day_zero_env(tmp_path)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "mastodon_is_my_blog", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env=env,
        input=stdin_text if stdin_text is not None else "",
        timeout=TIMEOUT_SECONDS,
        check=False,
    )


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return f"{result.stdout}\n{result.stderr}"


def real_mimb_dirs() -> list[Path]:
    from platformdirs import user_config_dir, user_data_dir

    dirs = {
        Path(user_data_dir(appname="mastodon_is_my_blog", appauthor=False)),
        Path(user_config_dir(appname="mastodon_is_my_blog", appauthor=False)),
    }
    return sorted(dirs)


def assert_no_traceback(result: subprocess.CompletedProcess[str]) -> None:
    output = combined_output(result)
    assert "Traceback (most recent call last)" not in output, f"day-0 user saw a traceback:\n{output}"
    # Isolation tripwire: if the subprocess mentions the developer's REAL
    # mimb data/config directory, MIMB_DATA_DIR/MIMB_CONFIG_DIR isolation is
    # broken and the suite may be reading (or writing!) real data — this
    # happened once: platformdirs ignores HOME/LOCALAPPDATA env overrides on
    # Windows. Never weaken this check.
    for real_dir in real_mimb_dirs():
        for variant in (str(real_dir), real_dir.as_posix()):
            assert variant.lower() not in output.lower(), f"day-0 subprocess touched the real mimb dir {variant}:\n{output}"


def test_bare_mimb_prints_help(tmp_path: Path) -> None:
    result = run_day_zero([], tmp_path)
    assert_no_traceback(result)
    assert result.returncode == 0
    assert "usage" in combined_output(result).lower()


def test_version_flag(tmp_path: Path) -> None:
    result = run_day_zero(["--version"], tmp_path)
    assert_no_traceback(result)
    assert result.returncode == 0


def test_version_command(tmp_path: Path) -> None:
    result = run_day_zero(["version"], tmp_path)
    assert_no_traceback(result)
    assert result.returncode == 0
    assert combined_output(result).strip()


def test_db_info_fresh_install(tmp_path: Path) -> None:
    result = run_day_zero(["db-info"], tmp_path)
    assert_no_traceback(result)
    assert result.returncode == 0, combined_output(result)
    assert "Database backend: sqlite" in result.stdout
    assert "app.db" in result.stdout
    assert "built-in default" in result.stdout


def test_auth_list_fresh_install(tmp_path: Path) -> None:
    result = run_day_zero(["auth", "list"], tmp_path)
    assert_no_traceback(result)
    assert result.returncode == 0, combined_output(result)


def test_admin_sync_fresh_install_advises_login(tmp_path: Path) -> None:
    result = run_day_zero(["admin", "sync"], tmp_path)
    assert_no_traceback(result)
    assert result.returncode == 1
    assert "auth login" in combined_output(result)


def test_doctor_fresh_install(tmp_path: Path) -> None:
    result = run_day_zero(["doctor"], tmp_path)
    assert_no_traceback(result)
    output = combined_output(result)
    assert result.returncode in (0, 1), output
    # Doctor's contract: every failing check line tells the user what to do.
    for line in output.splitlines():
        if line.startswith(("[FAIL]", "[warn]")):
            assert "fix:" in line or "skipped" in line or "nothing to do" in line, f"doctor line without advice: {line!r}"


def test_init_accepting_defaults_completes(tmp_path: Path) -> None:
    # "n" to changing the database, "n" to connecting an account now.
    result = run_day_zero(["init"], tmp_path, stdin_text="n\nn\n")
    assert_no_traceback(result)
    assert result.returncode == 0, combined_output(result)
    assert "Setup complete" in result.stdout


def test_init_custom_sqlite_path_takes_effect_same_process(tmp_path: Path) -> None:
    """The wizard's database choice must be used by the wizard itself —
    the pre-sprint bug initialized the OLD database and only honored the
    choice on the next run."""
    custom_db = (tmp_path / "chosen_day0.db").as_posix()
    # y (change storage), 1 (sqlite), path, n (no account now)
    result = run_day_zero(["init"], tmp_path, stdin_text=f"y\n1\n{custom_db}\nn\n")
    assert_no_traceback(result)
    assert result.returncode == 0, combined_output(result)
    assert Path(custom_db).exists(), "the DB chosen in the wizard was not the DB the wizard initialized"
    settings_env = tmp_path / "config" / "settings.env"
    assert settings_env.is_file()
    assert "DB_URL" in settings_env.read_text(encoding="utf-8")


def test_malformed_db_url_gives_advice_not_traceback(tmp_path: Path) -> None:
    result = run_day_zero(["db-info"], tmp_path, extra_env={"DB_URL": "definitely-not-a-url"})
    assert_no_traceback(result)
    assert result.returncode == 1
    output = combined_output(result)
    assert "DB_URL came from" in output
    assert "shell environment" in output


def test_unreachable_postgres_gives_advice_not_traceback(tmp_path: Path) -> None:
    result = run_day_zero(
        ["db-info"],
        tmp_path,
        extra_env={"DB_URL": "postgresql+asyncpg://mimb@127.0.0.1:9/nothere"},
    )
    assert_no_traceback(result)
    assert result.returncode == 1
    output = combined_output(result)
    assert "Could not use the database" in output
    assert "doctor" in output


def test_server_boots_on_fresh_install(tmp_path: Path) -> None:
    """`mimb start` day 0: the app must come up with zero configuration —
    no accounts, no env vars, no DuckDB extension cache, no spaCy model —
    and answer /api/status. Exercises the full lifespan startup."""
    boot_script = "from fastapi.testclient import TestClient\nfrom mastodon_is_my_blog.main import app\nwith TestClient(app) as client:\n    print('STATUS:', client.get('/api/status').json())\n"
    cwd = tmp_path / "cwd"
    cwd.mkdir(exist_ok=True)
    result = subprocess.run(
        [sys.executable, "-c", boot_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env=day_zero_env(tmp_path),
        timeout=TIMEOUT_SECONDS,
        check=False,
    )
    assert_no_traceback(result)
    assert result.returncode == 0, combined_output(result)
    assert "STATUS: {'status': 'up'}" in result.stdout
