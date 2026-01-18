import os
import re
from typing import Dict, NamedTuple


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
                base_url=fields["BASE_URL"],
                client_id=fields["CLIENT_ID"],
                client_secret=fields["CLIENT_SECRET"],
                access_token=fields.get("ACCESS_TOKEN"),
            )

    return results
