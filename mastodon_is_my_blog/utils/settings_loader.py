from __future__ import annotations

import os
import re
from typing import Dict, NamedTuple

from mastodon_is_my_blog.account_config import (
    ACCESS_TOKEN_FIELD,
    CLIENT_ID_FIELD,
    CLIENT_SECRET_FIELD,
    load_configured_accounts,
    normalize_base_url,
)
from mastodon_is_my_blog.credentials import get_credential


class IdentityConfig(NamedTuple):
    name: str  # The {NAME} from the env var
    base_url: str
    client_id: str
    client_secret: str
    access_token: str | None


def load_identities_from_env() -> Dict[str, IdentityConfig]:
    """
    Scans environment variables for the pattern:
    MASTODON_ID_{NAME}_{FIELD}

    Example .env:
    MASTODON_ID_MAIN_BASE_URL=https://mastodon.social
    MASTODON_ID_MAIN_CLIENT_ID=xyz...

    MASTODON_ID_ART_BASE_URL=https://art.social
    ...
    """
    identities: Dict[str, Dict[str, str]] = {}

    # Regex to capture NAME and FIELD (BASE_URL, CLIENT_ID, etc)
    pattern = re.compile(r"^MASTODON_ID_([A-Z0-9]+)_([A-Z_]+)$")

    for key, value in os.environ.items():
        match = pattern.match(key)
        if match:
            name = match.group(1)
            field = match.group(2)

            if name not in identities:
                identities[name] = {"name": name}

            identities[name][field] = value

    # Convert dicts to strongly typed objects, validating required fields
    results = {}
    for name, fields in identities.items():
        # Check required fields
        if "BASE_URL" in fields and "CLIENT_ID" in fields and "CLIENT_SECRET" in fields:
            results[name] = IdentityConfig(
                name=name,
                base_url=normalize_base_url(fields["BASE_URL"]),
                client_id=fields["CLIENT_ID"],
                client_secret=fields["CLIENT_SECRET"],
                access_token=fields.get("ACCESS_TOKEN"),
            )

    return results


def load_identities_from_keyring() -> Dict[str, IdentityConfig]:
    results: Dict[str, IdentityConfig] = {}

    for account in load_configured_accounts():
        client_id = get_credential(account.name, CLIENT_ID_FIELD)
        client_secret = get_credential(account.name, CLIENT_SECRET_FIELD)
        access_token = get_credential(account.name, ACCESS_TOKEN_FIELD)

        if not client_id or not client_secret:
            continue

        results[account.name] = IdentityConfig(
            name=account.name,
            base_url=account.base_url,
            client_id=client_id,
            client_secret=client_secret,
            access_token=access_token,
        )

    return results


def load_configured_identities() -> Dict[str, IdentityConfig]:
    identities = load_identities_from_keyring()
    identities.update(load_identities_from_env())
    return identities


def has_configured_identities() -> bool:
    if load_configured_accounts():
        return True
    return bool(load_identities_from_env())


def resolve_identity_config(
    config_name: str | None,
    *,
    base_url: str | None = None,
) -> IdentityConfig | None:
    configured_identities = load_configured_identities()
    if config_name and config_name in configured_identities:
        return configured_identities[config_name]

    if base_url:
        normalized_base_url = normalize_base_url(base_url)
        for identity in configured_identities.values():
            if identity.base_url == normalized_base_url:
                return identity

    return None
