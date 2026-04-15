from __future__ import annotations
import logging
import os

logger = logging.getLogger(__name__)
SERVICE = "mastodon_is_my_blog"


class KeyringError(RuntimeError):
    pass


def get_credential(name: str, field: str) -> str | None:
    """
    Retrieve a credential. Tries keyring first, then environment variable.
    Returns None if not found anywhere.
    """
    username = f"{name}:{field}"
    try:
        import keyring
        value = keyring.get_password(SERVICE, username)
        if value:
            return value
    except Exception as exc:
        logger.debug("keyring unavailable (%s), falling back to env", exc)

    env_key = f"MASTODON_ID_{name.upper()}_{field.upper()}"
    return os.environ.get(env_key)


def set_credential(name: str, field: str, value: str) -> bool:
    """
    Store a credential in the system keyring.
    Returns True on success, False if keyring is unavailable.
    """
    username = f"{name}:{field}"
    try:
        import keyring
        keyring.set_password(SERVICE, username, value)
        return True
    except Exception as exc:
        raise KeyringError(f"Could not store credential {field} for {name}") from exc


def delete_credential(name: str, field: str) -> bool:
    """Remove a credential from the keyring."""
    username = f"{name}:{field}"
    try:
        import keyring
        from keyring.errors import PasswordDeleteError

        keyring.delete_password(SERVICE, username)
        return True
    except PasswordDeleteError:
        return False
    except Exception as exc:
        raise KeyringError(f"Could not delete credential {field} for {name}") from exc
