from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from getpass import getpass
from importlib.metadata import version as pkg_version

from mastodon_is_my_blog.account_config import (
    ConfiguredAccount,
    delete_account_credentials,
    list_account_summaries,
    normalize_account_name,
    normalize_base_url,
    remove_configured_account,
    set_account_credentials,
    upsert_configured_account,
)
from mastodon_is_my_blog.credentials import get_credential
from mastodon_is_my_blog.db_port import DEFAULT_MODE, IMPORT_MODES
from mastodon_is_my_blog.utils.settings_loader import has_configured_identities


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mimb",
        description="Mastodon is My Blog — personal Mastodon reader and blog tool.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=pkg_version("mastodon_is_my_blog"),
    )
    subparsers = parser.add_subparsers(dest="command")

    start_parser = subparsers.add_parser("start", help="Start the web server.")
    start_parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    start_parser.add_argument("--port", default=8100, type=int, help="Bind port.")
    start_parser.add_argument(
        "--reload",
        dest="reload_",
        action="store_true",
        help="Enable auto-reload (dev).",
    )
    start_parser.add_argument(
        "--workers",
        default=1,
        type=int,
        help="Number of worker processes.",
    )
    start_parser.add_argument(
        "--no-open",
        action="store_true",
        help="Don't open the web UI in a browser.",
    )

    subparsers.add_parser("db-info", help="Show the resolved database path.")
    subparsers.add_parser("version", help="Show the installed package version.")
    subparsers.add_parser("init", help="Configure Mastodon accounts in keyring.")

    # auth: OAuth-first account management (Sprint 02).
    auth_parser = subparsers.add_parser("auth", help="Connect and manage Mastodon accounts.")
    auth_sub = auth_parser.add_subparsers(dest="auth_command")

    login_p = auth_sub.add_parser("login", help="Connect an account via browser OAuth — no client IDs needed.")
    login_p.add_argument("account", nargs="?", help="Your handle (user@server) or server URL.")
    login_p.add_argument("--name", help="Local account name (default: your Mastodon username).")
    login_p.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the authorize URL and paste the code by hand (SSH/headless).",
    )
    login_p.add_argument(
        "--manual",
        action="store_true",
        help="Advanced: type client ID/secret/token yourself (mock servers, pre-registered apps).",
    )

    auth_sub.add_parser("list", help="List configured accounts.")

    remove_p = auth_sub.add_parser("remove", help="Remove an account and its stored credentials.")
    remove_p.add_argument("name", help="Account name (see `mimb auth list`).")

    verify_p = auth_sub.add_parser("verify", help="Check that stored tokens still work.")
    verify_p.add_argument("name", nargs="?", help="Account name (default: all).")

    # admin: maintenance jobs from the terminal (Sprint 04).
    admin_parser = subparsers.add_parser("admin", help="Run maintenance jobs without the web UI.")
    admin_sub = admin_parser.add_subparsers(dest="admin_command")

    def add_admin(name: str, help_text: str):
        sub = admin_sub.add_parser(name, help=help_text)
        sub.add_argument("--account", help="Identity to act on (name or acct; default: first).")
        return sub

    sync_p = add_admin("sync", "Refresh cached follows, timeline, notifications, own posts.")
    sync_p.add_argument("--no-force", action="store_true", help="Skip if recently synced.")
    add_admin("download-friends", "Backfill the complete following + follower lists.")
    add_admin("download-notifications", "Backfill the complete notification history.")
    fav_p = add_admin("favourites", "Sync your outbound favourites.")
    fav_p.add_argument("--full", action="store_true", help="Walk the entire history, not just recent.")
    add_admin("rebin", "Recompute blog roll post/reply stats from cache (no API calls).")
    add_admin("backfill-flags", "Re-analyse cached posts for question/book flags (no API calls).")
    add_admin("nlp-backfill", "Precompute forum topic words with spaCy (no API calls).")
    catchup_p = add_admin("catchup", "Backfill post history for accounts you follow.")
    catchup_p.add_argument("--mode", choices=["urgent", "trickle"], default="urgent")
    catchup_p.add_argument("--max-accounts", type=int, help="Limit the queue length.")

    publish_parser = subparsers.add_parser("publish", help="Build the Eleventy blog into ./docs and git commit+push.")
    publish_parser.add_argument("--build-only", action="store_true", help="Build (and preview via `mimb start`) without committing.")
    publish_parser.add_argument("--pages-workflow", action="store_true", help="Also write the GitHub Pages deploy workflow.")
    publish_parser.add_argument("-m", "--message", default="Publish blog", help="Commit message.")

    subparsers.add_parser("doctor", help="Check the environment: database, accounts, node, git, spaCy.")

    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="Wipe mimb data left on this machine: home data/config, keyring entries, and optionally the Postgres database.",
    )
    uninstall_parser.add_argument("--dry-run", action="store_true", help="Show exactly what would be removed, change nothing.")
    uninstall_parser.add_argument("--yes", action="store_true", help="Wipe home data/config without prompting (keyring and Postgres still need their own flags).")
    uninstall_parser.add_argument("--keyring", action="store_true", help="Also delete mimb's OS keyring entries without prompting.")
    uninstall_parser.add_argument("--drop-db", action="store_true", help="Also DROP the Postgres database without prompting (Postgres backend only).")

    # db: backend-agnostic export / import / port / diff / verify (Phase 3).
    db_parser = subparsers.add_parser("db", help="Export/import/port data between storage backends.")
    db_sub = db_parser.add_subparsers(dest="db_command")

    export_p = db_sub.add_parser("export", help="Export the active DB to JSONL.")
    export_p.add_argument("--out", required=True, help="Output .jsonl path.")
    export_p.add_argument("--url", help="Source DB URL (default: active backend).")

    import_p = db_sub.add_parser("import", help="Import JSONL into a DB.")
    import_p.add_argument("--in", dest="in_", required=True, help="Input .jsonl path.")
    import_p.add_argument("--url", help="Target DB URL (default: active backend).")
    import_p.add_argument(
        "--mode",
        default=DEFAULT_MODE,
        choices=IMPORT_MODES,
        help="Conflict handling (default: upsert-newer).",
    )
    import_p.add_argument(
        "--force",
        action="store_true",
        help="Allow import into a non-empty DB for non-upsert modes.",
    )

    port_p = db_sub.add_parser("port", help="Copy one backend into another.")
    port_p.add_argument("--from", dest="from_url", required=True, help="Source DB URL.")
    port_p.add_argument("--to", dest="to_url", required=True, help="Target DB URL.")
    port_p.add_argument("--mode", default=DEFAULT_MODE, choices=IMPORT_MODES, help="Conflict handling.")
    port_p.add_argument("--force", action="store_true", help="Allow non-empty target.")

    for name, help_text in (
        ("diff", "Show tables that differ between two DBs."),
        ("verify", "Compare row counts + content hashes of two DBs."),
    ):
        cmp_p = db_sub.add_parser(name, help=help_text)
        cmp_p.add_argument("--left", dest="left_url", help="Left DB URL (default: active).")
        cmp_p.add_argument("--right", dest="right_url", required=True, help="Right DB URL.")
    return parser


def prompt_text(
    prompt: str,
    *,
    default: str | None = None,
    allow_empty: bool = False,
    secret: bool = False,
) -> str:
    prompt_suffix = f" [{default}]" if default else ""
    full_prompt = f"{prompt}{prompt_suffix}: "

    while True:
        value = getpass(full_prompt) if secret else input(full_prompt)
        if value:
            return value.strip()
        if default is not None:
            return default
        if allow_empty:
            return ""
        print("This value is required.")


def prompt_yes_no(prompt: str, *, default: bool = False) -> bool:
    prompt_suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        value = input(f"{prompt}{prompt_suffix}").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer yes or no.")


def save_account_interactively(existing_name: str | None = None) -> str:
    current_client_id = get_credential(existing_name, "client_id") if existing_name else None
    current_client_secret = get_credential(existing_name, "client_secret") if existing_name else None
    current_access_token = get_credential(existing_name, "access_token") if existing_name else None
    existing_base_url = None

    if existing_name:
        summaries_by_name = {summary.name: summary for summary in list_account_summaries()}
        existing_summary = summaries_by_name[existing_name]
        existing_base_url = existing_summary.base_url

    while True:
        try:
            account_name = normalize_account_name(prompt_text("Account name", default=existing_name))
            break
        except ValueError as exc:
            print(exc)

    while True:
        try:
            base_url = normalize_base_url(prompt_text("Mastodon instance URL", default=existing_base_url))
            break
        except ValueError as exc:
            print(exc)

    client_id = prompt_text("Client ID", default=current_client_id)
    client_secret = prompt_text(
        "Client secret",
        default=current_client_secret if current_client_secret else None,
        secret=True,
    )
    token_prompt = "Access token (press Enter to keep the current token)" if current_access_token else "Access token (optional; press Enter to skip)"
    access_token = prompt_text(
        token_prompt,
        allow_empty=True,
        secret=True,
    )
    final_access_token = access_token if access_token else current_access_token

    upsert_configured_account(ConfiguredAccount(name=account_name, base_url=base_url))
    set_account_credentials(
        account_name,
        client_id=client_id,
        client_secret=client_secret,
        access_token=final_access_token,
    )

    if existing_name and existing_name != account_name:
        remove_configured_account(existing_name)
        delete_account_credentials(existing_name)

    return account_name


async def sync_identity_state() -> None:
    # Imported here, not at module top: importing store binds DB_URL and
    # builds the engine, which must happen AFTER the init wizard has had a
    # chance to write DB_URL — and commands like `mimb auth list` should not
    # touch the database at all.
    from mastodon_is_my_blog.store import (
        get_or_create_default_meta_account,
        init_db,
        sync_configured_identities,
    )

    await init_db()
    # Stamp a freshly-created DB at the Alembic head (Phase 2) so future
    # `alembic upgrade` runs behave; no-op if already stamped.
    from mastodon_is_my_blog.db_init import ensure_schema_stamped

    await ensure_schema_stamped()
    await get_or_create_default_meta_account()
    await sync_configured_identities()


def normalize_postgres_url(url: str) -> str:
    """postgresql:// or postgres:// -> the async driver URL SQLAlchemy needs."""
    for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    raise ValueError("That doesn't look like a Postgres URL. Expected something like postgresql://user:pass@localhost:5432/mimb.")


def write_db_url_to_env(db_url: str) -> None:
    """Persist DB_URL to the per-user settings file and apply it to this
    process so the rest of the wizard uses the chosen database."""
    import os

    from dotenv import set_key

    from mastodon_is_my_blog.environment import get_settings_env_path

    settings_path = get_settings_env_path(create_dir=True)
    set_key(str(settings_path), "DB_URL", db_url)
    os.environ["DB_URL"] = db_url
    print(f"Saved DB_URL to {settings_path}")
    print("This applies wherever you run mimb; a DB_URL shell variable or a ./.env file still overrides it.")


def prompt_database_setup() -> None:
    from mastodon_is_my_blog.db_path import get_default_db_url

    print(f"Database: {get_default_db_url()}")
    if not prompt_yes_no("Change where your data is stored?", default=False):
        return

    print("1. SQLite — a single local file, no setup needed (recommended)")
    print("2. Postgres — you already run a Postgres server")
    while True:
        choice = input("Which database? [1-2]: ").strip()
        if choice in {"1", "2"}:
            break
        print("Please answer 1 or 2.")

    if choice == "1":
        path = prompt_text("SQLite file path", allow_empty=True)
        if path:
            write_db_url_to_env(f"sqlite+aiosqlite:///{path}")
        else:
            print("Keeping the default SQLite location.")
        return

    while True:
        raw = prompt_text("Postgres URL (postgresql://user:pass@host:5432/dbname)")
        try:
            write_db_url_to_env(normalize_postgres_url(raw))
            return
        except ValueError as exc:
            print(exc)


def run_init_command() -> int:
    print("Welcome to mimb setup.")
    prompt_database_setup()

    summaries = list_account_summaries()
    if summaries:
        print("Configured accounts:")
        for summary in summaries:
            token_label = "token saved" if summary.has_access_token else "needs login"
            print(f"- {summary.name} ({summary.base_url}, {token_label})")
        print("Manage them with: mimb auth list | login | remove | verify")
    elif prompt_yes_no("Connect a Mastodon account now? (opens your browser — no keys to type)", default=True):
        from mastodon_is_my_blog import auth_cli

        auth_cli.run_login(None)
    else:
        print("Skipped. You can connect later with `mimb auth login your@handle`, or from the web UI (Connect Account).")

    try:
        asyncio.run(sync_identity_state())
    except Exception as exc:  # noqa: BLE001 - setup must end with advice, not a traceback
        print(db_failure_advice(exc))
        return 1
    print("Setup complete. Run `mimb start` and open http://127.0.0.1:8100")
    return 0


def db_failure_advice(exc: Exception) -> str:
    """One consistent 'what happened / what to do' block for DB failures."""
    from mastodon_is_my_blog.environment import describe_setting_source

    return f"Could not use the database ({exc}).\nDB_URL came from: {describe_setting_source('DB_URL')}.\nIf you configured Postgres, check that the server is running and the URL is correct.\nRun `mimb db-info` to see the configured location, or `mimb doctor` for a full checkup."


def display_url(host: str, port: int) -> str:
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    return f"http://{display_host}:{port}"


def is_mimb_responding(url: str, timeout: float = 1.0) -> bool:
    """True if a mimb server (specifically) answers at url."""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(f"{url}/api/status", timeout=timeout) as response:
            return json.load(response).get("status") == "up"
    except Exception:  # noqa: BLE001 - anything short of "up" means no
        return False


def print_account_status(url: str) -> None:
    try:
        summaries = list_account_summaries()
    except Exception as exc:  # noqa: BLE001 - keyring trouble must not block startup
        print(f"Could not read configured accounts ({exc}). Run `mimb doctor` for details.")
        return

    if summaries:
        print("Configured accounts:")
        for summary in summaries:
            status = "ready" if summary.has_access_token else "needs login — run `mimb auth login`"
            print(f"- {summary.name} ({summary.base_url}, {status})")
    elif has_configured_identities():
        print("Accounts configured via environment variables.")
    else:
        print(f"No Mastodon account connected yet — click “Connect Account” at {url}, or run `mimb auth login your@handle`.")


def open_browser_when_ready(url: str, timeout: float = 30.0) -> None:
    """Wait for the server to answer, then open the web UI (runs in a thread)."""
    import time
    import webbrowser

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_mimb_responding(url):
            webbrowser.open(url)
            return
        time.sleep(0.5)


def start_server(host: str, port: int, reload_: bool, workers: int, no_open: bool = False) -> None:
    import threading
    import webbrowser

    import uvicorn

    url = display_url(host, port)

    if is_mimb_responding(url):
        print(f"mimb is already running at {url} — nothing to start.")
        if not no_open:
            print("Opening your browser.")
            webbrowser.open(url)
        return

    print(f"Starting mastodon_is_my_blog on {url}")
    print_account_status(url)
    if not no_open and not reload_:
        threading.Thread(target=open_browser_when_ready, args=(url,), daemon=True).start()
    uvicorn.run(
        "mastodon_is_my_blog.main:app",
        host=host,
        port=port,
        reload=reload_,
        workers=workers if not reload_ else 1,
    )


def show_db_info() -> int:
    from mastodon_is_my_blog.environment import describe_setting_source
    from mastodon_is_my_blog.schema_version import describe_database

    try:
        info = asyncio.run(describe_database())
    except Exception as exc:  # noqa: BLE001 - db-info is a diagnostic, it must not traceback
        print(db_failure_advice(exc))
        return 1
    print(f"Database backend: {info['backend']}")
    print(f"Database URL:     {info['url']}")
    print(f"DB_URL source:    {describe_setting_source('DB_URL')}")
    print(f"Schema version:   {info['schema_version']}")
    if info["remote_sync"] != "n/a":
        print(f"Remote sync:      {info['remote_sync']}")
    return 0


def run_db_command(args: argparse.Namespace) -> int:
    from pathlib import Path
    from tempfile import NamedTemporaryFile

    from mastodon_is_my_blog import db_port

    command = getattr(args, "db_command", None)

    if command == "export":
        counts = asyncio.run(db_port.export_jsonl(Path(args.out), url=args.url))
        total = sum(counts.values())
        print(f"Exported {total} rows across {len(counts)} tables to {args.out}")
        return 0

    if command == "import":
        written = asyncio.run(db_port.import_jsonl(Path(args.in_), url=args.url, mode=args.mode, force=args.force))
        total = sum(written.values())
        print(f"Imported {total} rows across {len(written)} tables (mode={args.mode})")
        return 0

    if command == "port":
        with NamedTemporaryFile(suffix=".jsonl", delete=False) as handle:
            tmp = Path(handle.name)
        try:
            result = asyncio.run(
                db_port.port(
                    from_url=args.from_url,
                    to_url=args.to_url,
                    tmp_path=tmp,
                    mode=args.mode,
                    force=args.force,
                )
            )
        finally:
            tmp.unlink(missing_ok=True)
        total = sum(result["written"].values())
        print(f"Ported {total} rows from {args.from_url} to {args.to_url}")
        return 0

    if command in ("diff", "verify"):
        fn = db_port.diff if command == "diff" else db_port.verify
        report = asyncio.run(fn(args.left_url, args.right_url))
        if command == "diff" and not report:
            print("No differences: the two databases match.")
            return 0
        print(db_port.format_verify_report(report))
        all_match = all(r["hash_match"] and r["left_rows"] == r["right_rows"] for r in report)
        return 0 if (command == "diff" or all_match) else 1

    print("Usage: mimb db {export|import|port|diff|verify} ...")
    return 2


def run_auth_command(args: argparse.Namespace) -> int:
    from mastodon_is_my_blog import auth_cli

    command = getattr(args, "auth_command", None)

    if command == "login":
        account_name: str | None
        if args.manual:
            account_name = save_account_interactively()
        else:
            account_name = auth_cli.run_login(args.account, name=args.name, no_browser=args.no_browser)
        if account_name is None:
            return 1
        try:
            asyncio.run(sync_identity_state())
        except Exception as exc:  # noqa: BLE001 - the token is saved; report the DB problem with advice
            print("Your account is connected and the token is saved, but syncing it into the database failed.")
            print(db_failure_advice(exc))
            return 1
        return 0

    if command == "list":
        return auth_cli.run_list()

    if command == "remove":
        return auth_cli.run_remove(args.name)

    if command == "verify":
        return auth_cli.run_verify(args.name)

    print("Usage: mimb auth {login|list|remove|verify} ...")
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    command = args.command

    if command == "db":
        return run_db_command(args)

    if command == "auth":
        return run_auth_command(args)

    if command in {"admin", "publish", "doctor"}:
        from mastodon_is_my_blog import admin_cli

        if command == "admin":
            return admin_cli.run_admin_command(args)
        if command == "publish":
            return admin_cli.run_publish_command(args)
        return admin_cli.run_doctor_command()

    if command == "start":
        start_server(args.host, args.port, args.reload_, args.workers, args.no_open)
        return 0

    if command == "db-info":
        return show_db_info()

    if command == "version":
        print(pkg_version("mastodon_is_my_blog"))
        return 0

    if command == "init":
        return run_init_command()

    if command == "uninstall":
        from mastodon_is_my_blog.uninstall_cli import run_uninstall

        return run_uninstall(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
