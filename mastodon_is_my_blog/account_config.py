from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir

from mastodon_is_my_blog.credentials import (
    delete_credential,
    get_credential,
    set_credential,
)

CLIENT_ID_FIELD = "client_id"
CLIENT_SECRET_FIELD = "client_secret"
ACCESS_TOKEN_FIELD = "access_token"
ACCOUNT_FIELDS = (CLIENT_ID_FIELD, CLIENT_SECRET_FIELD, ACCESS_TOKEN_FIELD)


@dataclass(frozen=True)
class ConfiguredAccount:
    name: str
    base_url: str


@dataclass(frozen=True)
class ConfiguredAccountSummary:
    name: str
    base_url: str
    has_client_id: bool
    has_client_secret: bool
    has_access_token: bool


def get_accounts_config_path() -> Path:
    config_dir = Path(user_config_dir(appname="mastodon_is_my_blog", appauthor=False))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "accounts.json"


def normalize_account_name(name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_").upper()
    if not normalized:
        raise ValueError("Account name must include at least one letter or number.")
    return normalized


def normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized.startswith(("http://", "https://")):
        raise ValueError("Base URL must start with http:// or https://.")
    return normalized


def load_configured_accounts() -> list[ConfiguredAccount]:
    config_path = get_accounts_config_path()
    if not config_path.exists():
        return []

    data = json.loads(config_path.read_text(encoding="utf-8"))
    raw_accounts = data.get("accounts", [])
    accounts: list[ConfiguredAccount] = []

    for raw_account in raw_accounts:
        if not isinstance(raw_account, dict):
            continue

        raw_name = raw_account.get("name")
        raw_base_url = raw_account.get("base_url")
        if not isinstance(raw_name, str) or not isinstance(raw_base_url, str):
            continue

        accounts.append(
            ConfiguredAccount(
                name=normalize_account_name(raw_name),
                base_url=normalize_base_url(raw_base_url),
            )
        )

    return sorted(accounts, key=lambda account: account.name)


def save_configured_accounts(accounts: list[ConfiguredAccount]) -> None:
    config_path = get_accounts_config_path()
    payload = {
        "accounts": [
            {"name": account.name, "base_url": account.base_url}
            for account in sorted(accounts, key=lambda account: account.name)
        ]
    }
    config_path.write_text(f"{json.dumps(payload, indent=2)}\n", encoding="utf-8")


def upsert_configured_account(account: ConfiguredAccount) -> None:
    normalized_account = ConfiguredAccount(
        name=normalize_account_name(account.name),
        base_url=normalize_base_url(account.base_url),
    )
    accounts = {existing.name: existing for existing in load_configured_accounts()}
    accounts[normalized_account.name] = normalized_account
    save_configured_accounts(list(accounts.values()))


def remove_configured_account(name: str) -> None:
    normalized_name = normalize_account_name(name)
    accounts = [
        account
        for account in load_configured_accounts()
        if account.name != normalized_name
    ]
    save_configured_accounts(accounts)


def list_account_summaries() -> list[ConfiguredAccountSummary]:
    summaries: list[ConfiguredAccountSummary] = []
    for account in load_configured_accounts():
        summaries.append(
            ConfiguredAccountSummary(
                name=account.name,
                base_url=account.base_url,
                has_client_id=bool(get_credential(account.name, CLIENT_ID_FIELD)),
                has_client_secret=bool(
                    get_credential(account.name, CLIENT_SECRET_FIELD)
                ),
                has_access_token=bool(get_credential(account.name, ACCESS_TOKEN_FIELD)),
            )
        )
    return summaries


def set_account_credentials(
    name: str,
    *,
    client_id: str,
    client_secret: str,
    access_token: str | None,
) -> None:
    normalized_name = normalize_account_name(name)
    set_credential(normalized_name, CLIENT_ID_FIELD, client_id.strip())
    set_credential(normalized_name, CLIENT_SECRET_FIELD, client_secret.strip())

    if access_token:
        set_credential(normalized_name, ACCESS_TOKEN_FIELD, access_token.strip())
    else:
        delete_credential(normalized_name, ACCESS_TOKEN_FIELD)


def delete_account_credentials(name: str) -> None:
    normalized_name = normalize_account_name(name)
    for field in ACCOUNT_FIELDS:
        delete_credential(normalized_name, field)


def build_unique_account_name(
    preferred_name: str,
    existing_names: set[str],
) -> str:
    base_name = normalize_account_name(preferred_name)
    candidate = base_name
    suffix = 2
    while candidate in existing_names:
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    return candidate
