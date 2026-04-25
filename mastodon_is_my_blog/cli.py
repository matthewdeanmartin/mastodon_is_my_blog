from __future__ import annotations

import argparse
import asyncio
from getpass import getpass
from importlib.metadata import version as pkg_version
from collections.abc import Sequence

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
from mastodon_is_my_blog.store import (
    get_or_create_default_meta_account,
    init_db,
    sync_configured_identities,
)
from mastodon_is_my_blog.utils.settings_loader import has_configured_identities


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mastodon_is_my_blog",
        description="Mastodon is My Blog — personal Mastodon reader and blog tool.",
    )
    subparsers = parser.add_subparsers(dest="command")

    start_parser = subparsers.add_parser("start", help="Start the web server.")
    start_parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    start_parser.add_argument("--port", default=8000, type=int, help="Bind port.")
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

    subparsers.add_parser("db-info", help="Show the resolved database path.")
    subparsers.add_parser("version", help="Show the installed package version.")
    subparsers.add_parser("init", help="Configure Mastodon accounts in keyring.")
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


def choose_account(prompt: str) -> str:
    summaries = list_account_summaries()
    for index, summary in enumerate(summaries, start=1):
        token_label = "token saved" if summary.has_access_token else "needs login"
        print(f"{index}. {summary.name} ({summary.base_url}, {token_label})")

    while True:
        choice = input(f"{prompt} [1-{len(summaries)}]: ").strip()
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(summaries):
                return summaries[index - 1].name
        print("Please choose one of the listed accounts.")


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
    await init_db()
    await get_or_create_default_meta_account()
    await sync_configured_identities()


def run_init_command() -> None:
    summaries = list_account_summaries()

    if not summaries:
        print("Welcome. Let's set up your Mastodon accounts.")
        while True:
            save_account_interactively()
            if not prompt_yes_no("Add another account?"):
                break
    else:
        print("Configured accounts:")
        for index, summary in enumerate(summaries, start=1):
            token_label = "token saved" if summary.has_access_token else "needs login"
            print(f"{index}. {summary.name} ({summary.base_url}, {token_label})")

        while list_account_summaries() and prompt_yes_no("Do you want to change an existing account?"):
            selected_name = choose_account("Which account do you want to change?")
            save_account_interactively(selected_name)

        while list_account_summaries() and prompt_yes_no("Do you want to delete an account?"):
            selected_name = choose_account("Which account do you want to delete?")
            remove_configured_account(selected_name)
            delete_account_credentials(selected_name)
            print(f"Deleted {selected_name}.")

        while prompt_yes_no("Do you want to add another account?"):
            save_account_interactively()

    asyncio.run(sync_identity_state())


def start_server(host: str, port: int, reload_: bool, workers: int) -> None:
    import uvicorn

    print(f"Starting mastodon_is_my_blog on http://{host}:{port}")
    uvicorn.run(
        "mastodon_is_my_blog.main:app",
        host=host,
        port=port,
        reload=reload_,
        workers=workers if not reload_ else 1,
    )


def show_db_info() -> None:
    from mastodon_is_my_blog.db_path import get_default_db_url

    url = get_default_db_url()
    print(f"DB_URL: {url}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    command = args.command
    if command not in {"init", "db-info", "version"} and not has_configured_identities():
        print("No configured Mastodon accounts found. Starting setup.")
        run_init_command()

    if command == "start":
        start_server(args.host, args.port, args.reload_, args.workers)
        return 0

    if command == "db-info":
        show_db_info()
        return 0

    if command == "version":
        print(pkg_version("mastodon_is_my_blog"))
        return 0

    if command == "init":
        run_init_command()
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
