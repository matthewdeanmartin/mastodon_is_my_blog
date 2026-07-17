"""`mimb uninstall`: wipe what running mimb left on this machine — for broken
installs and clean goodbyes.

Three distinct, separately confirmed steps:

1. home data & config — the platformdirs data/config directories (SQLite
   database, accounts.json, caches), plus a custom-located SQLite file when
   DB_URL points outside them.
2. keyring — every mimb credential in the OS keyring, listed key by key
   before anything is deleted.
3. postgres — DROP DATABASE, offered only when the active backend is
   Postgres and the server actually answers.

The installed program itself is not touched — that's
`pipx uninstall mastodon-is-my-blog` (or pip) afterwards. Neither are .env
files in project directories nor published blog output (docs/).
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from mastodon_is_my_blog.account_config import ACCOUNT_FIELDS, load_configured_accounts
from mastodon_is_my_blog.credentials import SERVICE, delete_credential

APP_NAME = "mastodon_is_my_blog"
TURSO_TOKEN_KEY = "turso-auth-token"


@dataclass
class UninstallPlan:
    directories: list[Path] = field(default_factory=list)
    extra_files: list[Path] = field(default_factory=list)
    keyring_entries: list[str] = field(default_factory=list)
    postgres_url: str | None = None
    postgres_display: str | None = None
    postgres_db: str | None = None
    postgres_error: str | None = None

    def has_home_data(self) -> bool:
        return bool(self.directories or self.extra_files)


def home_directories() -> list[Path]:
    """Data + config dirs (identical on Windows; deduped). Uses the same
    resolution as the app itself, so MIMB_DATA_DIR/MIMB_CONFIG_DIR overrides
    wipe the directories mimb actually used."""
    from mastodon_is_my_blog.environment import get_config_dir, get_data_dir

    dirs: list[Path] = []
    for raw in (get_data_dir(), get_config_dir()):
        path = Path(raw).resolve()
        if path.exists() and path not in dirs:
            dirs.append(path)
    return dirs


def custom_sqlite_file(directories: list[Path]) -> Path | None:
    """A DB_URL-configured SQLite file living outside the wiped dirs."""
    import os

    url = os.environ.get("DB_URL", "")
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            path = Path(url[len(prefix) :]).resolve()
            if path.exists() and not any(parent in directories for parent in (path, *path.parents)):
                return path
    return None


def list_keyring_entries() -> list[str]:
    """The keyring usernames mimb owns that actually hold a value right now.
    Probes keyring directly — get_credential's env fallback would report
    values that aren't keyring entries at all."""
    try:
        import keyring
    except ImportError:
        return []

    candidates = [f"{account.name}:{field_name}" for account in load_configured_accounts() for field_name in ACCOUNT_FIELDS]
    candidates.append(TURSO_TOKEN_KEY)

    entries = []
    for username in candidates:
        try:
            if keyring.get_password(SERVICE, username):
                entries.append(username)
        except Exception:  # noqa: BLE001 - a broken keyring means nothing to wipe
            return []
    return entries


def directory_size_mb(path: Path) -> float:
    total = 0
    for file_path in path.rglob("*"):
        try:
            if file_path.is_file():
                total += file_path.stat().st_size
        except OSError:
            continue
    return total / (1024 * 1024)


async def probe_postgres(url: str) -> str | None:
    """None when the server answers, else the error message."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url, connect_args={"timeout": 5})
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return None
    except Exception as exc:  # noqa: BLE001 - report, don't crash
        return str(exc).splitlines()[0]
    finally:
        await engine.dispose()


async def drop_postgres_database(url: str) -> tuple[bool, str]:
    """Connect to the server's maintenance DB and drop the mimb database.
    WITH (FORCE) (PG 13+) kicks lingering connections; falls back for older
    servers."""
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine

    url_obj = make_url(url)
    dbname = url_obj.database
    if not dbname:
        return False, "No database name in the connection URL."
    quoted = dbname.replace('"', '""')

    engine = create_async_engine(url_obj.set(database="postgres"), isolation_level="AUTOCOMMIT", connect_args={"timeout": 10})
    try:
        async with engine.connect() as conn:
            try:
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{quoted}" WITH (FORCE)'))
            except Exception:  # noqa: BLE001 - pre-13 servers reject WITH (FORCE)
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{quoted}"'))
        return True, f'Dropped database "{dbname}".'
    except Exception as exc:  # noqa: BLE001
        return False, f"Drop failed: {str(exc).splitlines()[0]}"
    finally:
        await engine.dispose()


def gather_plan() -> UninstallPlan:
    plan = UninstallPlan()
    plan.directories = home_directories()
    extra = custom_sqlite_file(plan.directories)
    if extra is not None:
        plan.extra_files.append(extra)
    plan.keyring_entries = list_keyring_entries()

    from mastodon_is_my_blog.db_path import get_default_db_url

    try:
        url = get_default_db_url()
    except Exception:  # noqa: BLE001 - misconfigured backend: nothing to offer
        url = ""
    if url.startswith(("postgresql", "postgres")):
        from sqlalchemy.engine import make_url

        url_obj = make_url(url)
        plan.postgres_url = url
        plan.postgres_db = url_obj.database
        plan.postgres_display = url_obj.render_as_string(hide_password=True)
        plan.postgres_error = asyncio.run(probe_postgres(url))
    return plan


def print_plan(plan: UninstallPlan) -> None:
    print("mimb uninstall — this is what would be removed:")
    print()
    print("Step 1 — home data & config (database, accounts.json, caches):")
    if plan.has_home_data():
        for directory in plan.directories:
            print(f"  - {directory}  ({directory_size_mb(directory):.1f} MB, entire directory)")
        for extra in plan.extra_files:
            print(f"  - {extra}  (SQLite database at custom DB_URL location)")
    else:
        print("  (nothing found)")
    print()
    print(f'Step 2 — OS keyring entries (service "{SERVICE}"):')
    if plan.keyring_entries:
        for entry in plan.keyring_entries:
            print(f"  - {entry}")
    else:
        print("  (none found)")
    print()
    print("Step 3 — Postgres database:")
    if plan.postgres_url is None:
        print("  (not using the Postgres backend — nothing to drop)")
    elif plan.postgres_error is not None:
        print(f"  {plan.postgres_display}")
        print(f"  Cannot connect ({plan.postgres_error}) — the drop will not be offered.")
    else:
        print(f'  DROP DATABASE "{plan.postgres_db}" on {plan.postgres_display}')
    print()
    print("Not touched: the installed program (remove it afterwards with")
    print("`pipx uninstall mastodon-is-my-blog`), .env files in your project")
    print("directories, and any published blog output (docs/).")
    print()


def wipe_home_data(plan: UninstallPlan) -> bool:
    ok = True
    for directory in plan.directories:
        try:
            shutil.rmtree(directory)
            print(f"Removed {directory}")
        except OSError as exc:
            print(f"Could not remove {directory}: {exc}")
            ok = False
    for extra in plan.extra_files:
        try:
            extra.unlink()
            print(f"Removed {extra}")
        except OSError as exc:
            print(f"Could not remove {extra}: {exc}")
            ok = False
    return ok


def wipe_keyring(entries: list[str]) -> bool:
    import keyring

    ok = True
    for entry in entries:
        try:
            if entry == TURSO_TOKEN_KEY:
                keyring.delete_password(SERVICE, TURSO_TOKEN_KEY)
            else:
                name, field_name = entry.split(":", 1)
                delete_credential(name, field_name)
            print(f"Removed keyring entry {entry}")
        except Exception as exc:  # noqa: BLE001
            print(f"Could not remove keyring entry {entry}: {exc}")
            ok = False
    return ok


def run_uninstall(args) -> int:
    from mastodon_is_my_blog.cli import prompt_yes_no

    plan = gather_plan()
    print_plan(plan)

    if args.dry_run:
        print("Dry run — nothing was changed. Run without --dry-run to uninstall;")
        print("add --yes (home wipe), --keyring, and --drop-db to skip the prompts.")
        return 0

    ok = True

    # Step 1: home data & config.
    if not plan.has_home_data():
        print("Step 1: no home data found — nothing to wipe.")
    elif args.yes or prompt_yes_no("Step 1: wipe the home data & config listed above?"):
        ok = wipe_home_data(plan) and ok
    else:
        print("Step 1 skipped.")

    # Step 2: keyring — its own confirmation, never implied by --yes.
    if not plan.keyring_entries:
        print("Step 2: no keyring entries found.")
    elif args.keyring or (not args.yes and prompt_yes_no(f"Step 2: delete the {len(plan.keyring_entries)} keyring entr{'y' if len(plan.keyring_entries) == 1 else 'ies'} listed above?")):
        ok = wipe_keyring(plan.keyring_entries) and ok
    else:
        print("Step 2 skipped (pass --keyring to include it).")

    # Step 3: postgres — its own confirmation, never implied by --yes.
    if plan.postgres_url is None:
        print("Step 3: not on the Postgres backend — nothing to drop.")
    elif plan.postgres_error is not None:
        print("Step 3 skipped: Postgres is configured but unreachable.")
    elif args.drop_db or (not args.yes and prompt_yes_no(f'Step 3: DROP the Postgres database "{plan.postgres_db}"?')):
        dropped, detail = asyncio.run(drop_postgres_database(plan.postgres_url))
        print(detail)
        ok = dropped and ok
    else:
        print("Step 3 skipped (pass --drop-db to include it).")

    print()
    print("Done. To remove the program itself: pipx uninstall mastodon-is-my-blog")
    return 0 if ok else 1
