import os

from mastodon_is_my_blog.account_config import ConfiguredAccount
from mastodon_is_my_blog.utils.settings_loader import (
    IdentityConfig,
    load_identities_from_env,
    load_identities_from_keyring,
)


def test_load_identities_from_env_reads_complete_groups(monkeypatch) -> None:
    for key in list(os.environ):
        if key.startswith("MASTODON_ID_"):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("MASTODON_ID_MAIN_BASE_URL", "https://mastodon.social")
    monkeypatch.setenv("MASTODON_ID_MAIN_CLIENT_ID", "main-client")
    monkeypatch.setenv("MASTODON_ID_MAIN_CLIENT_SECRET", "main-secret")
    monkeypatch.setenv("MASTODON_ID_MAIN_ACCESS_TOKEN", "main-token")
    monkeypatch.setenv("MASTODON_ID_ART_BASE_URL", "https://art.example")
    monkeypatch.setenv("MASTODON_ID_ART_CLIENT_ID", "art-client")
    monkeypatch.setenv("MASTODON_ID_ART_CLIENT_SECRET", "art-secret")

    identities = load_identities_from_env()

    assert identities == {
        "MAIN": IdentityConfig(
            name="MAIN",
            base_url="https://mastodon.social",
            client_id="main-client",
            client_secret="main-secret",
            access_token="main-token",
        ),
        "ART": IdentityConfig(
            name="ART",
            base_url="https://art.example",
            client_id="art-client",
            client_secret="art-secret",
            access_token=None,
        ),
    }


def test_load_identities_from_env_ignores_invalid_and_incomplete_entries(
    monkeypatch,
) -> None:
    for key in list(os.environ):
        if key.startswith("MASTODON_ID_"):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("MASTODON_ID_BAD_BASE_URL", "https://broken.example")
    monkeypatch.setenv("MASTODON_ID_BAD_CLIENT_ID", "missing-secret")
    monkeypatch.setenv("MASTODON_ID_name_CLIENT_ID", "lowercase-name")
    monkeypatch.setenv("UNRELATED_SETTING", "value")

    identities = load_identities_from_env()

    assert identities == {}


def test_load_identities_from_keyring_reads_saved_accounts(monkeypatch) -> None:
    monkeypatch.setattr(
        "mastodon_is_my_blog.utils.settings_loader.load_configured_accounts",
        lambda: [ConfiguredAccount(name="MAIN", base_url="https://mastodon.social")],
    )

    def fake_get_credential(name: str, field: str) -> str | None:
        values = {
            ("MAIN", "client_id"): "main-client",
            ("MAIN", "client_secret"): "main-secret",
            ("MAIN", "access_token"): "main-token",
        }
        return values.get((name, field))

    monkeypatch.setattr(
        "mastodon_is_my_blog.utils.settings_loader.get_credential",
        fake_get_credential,
    )

    identities = load_identities_from_keyring()

    assert identities == {
        "MAIN": IdentityConfig(
            name="MAIN",
            base_url="https://mastodon.social",
            client_id="main-client",
            client_secret="main-secret",
            access_token="main-token",
        )
    }
