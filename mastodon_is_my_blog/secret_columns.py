"""Encryption at rest for credential columns.

Single-user (local) installs usually have no ``TOKEN_ENCRYPTION_KEY`` and
store values as-is — the OS keyring is the local secret store, and the
SQLite file never leaves the machine. Hosted (server-mode) deployments must
set ``TOKEN_ENCRYPTION_KEY`` (a Fernet key; generate with
``python -m mastodon_is_my_blog.secret_columns``); credential columns are
then envelope-encrypted before they touch disk.

Encrypted values carry an explicit ``enc:v1:`` prefix so that:
- legacy plaintext rows keep reading correctly after a key is introduced,
- rows written with a key fail loudly (not silently as garbage) if the key
  disappears.
"""

from __future__ import annotations

import os

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from mastodon_is_my_blog.tenancy import is_server_mode

ENCRYPTED_PREFIX = "enc:v1:"

# (key material, cipher) — rebuilt when the env var changes (tests do this).
cipher_cache: tuple[str, object] | None = None


def get_cipher():
    """Return a Fernet cipher for TOKEN_ENCRYPTION_KEY, or None if unset."""
    global cipher_cache  # pylint: disable=global-statement
    key = os.environ.get("TOKEN_ENCRYPTION_KEY")
    if not key:
        return None
    if cipher_cache is not None and cipher_cache[0] == key:
        return cipher_cache[1]

    from cryptography.fernet import Fernet

    cipher = Fernet(key.encode("utf-8"))
    cipher_cache = (key, cipher)
    return cipher


class EncryptedString(TypeDecorator):
    """String column that is Fernet-encrypted at rest when a key is configured.

    - Key set: writes are encrypted; reads decrypt ``enc:v1:`` values and
      pass legacy plaintext through unchanged.
    - No key, single-user mode: transparent passthrough (current behavior).
    - No key, server mode: refuses to write plaintext credentials.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or value == "":
            return value
        cipher = get_cipher()
        if cipher is None:
            if is_server_mode():
                raise RuntimeError("Refusing to store a plaintext credential in server mode: TOKEN_ENCRYPTION_KEY is not set")
            return value
        token = cipher.encrypt(value.encode("utf-8")).decode("ascii")
        return f"{ENCRYPTED_PREFIX}{token}"

    def process_result_value(self, value, dialect):
        if value is None or not value.startswith(ENCRYPTED_PREFIX):
            return value
        cipher = get_cipher()
        if cipher is None:
            raise RuntimeError("Encountered an encrypted credential but TOKEN_ENCRYPTION_KEY is not set")
        from cryptography.fernet import InvalidToken

        raw = value[len(ENCRYPTED_PREFIX) :].encode("ascii")
        try:
            return cipher.decrypt(raw).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("Failed to decrypt a credential: TOKEN_ENCRYPTION_KEY does not match the key that wrote it") from exc


def generate_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("ascii")


if __name__ == "__main__":
    print(generate_key())
