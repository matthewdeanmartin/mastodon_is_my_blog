from __future__ import annotations

import threading
import urllib.error
import urllib.request

from mastodon_is_my_blog import auth_cli
from mastodon_is_my_blog.account_config import load_configured_accounts


class FakeMastodon:
    """Stands in for mastodon.Mastodon in auth_cli: records the OAuth dance."""

    created_apps: list[dict] = []

    def __init__(self, api_base_url=None, client_id=None, client_secret=None, access_token=None):
        self.api_base_url = api_base_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token

    @staticmethod
    def create_app(client_name, scopes, redirect_uris, api_base_url):
        FakeMastodon.created_apps.append(
            {
                "client_name": client_name,
                "scopes": scopes,
                "redirect_uris": redirect_uris,
                "api_base_url": api_base_url,
            }
        )
        return ("generated-client-id", "generated-client-secret")

    def auth_request_url(self, redirect_uris, scopes, state=None, allow_http=False):
        return f"{self.api_base_url}/oauth/authorize?redirect_uri={redirect_uris}&state={state}"

    def log_in(self, code, redirect_uri, scopes, allow_http=False):
        assert code == "pasted-code"
        return "granted-access-token"

    def account_verify_credentials(self):
        return {"username": "mistersql", "acct": "mistersql"}


def isolate_config(monkeypatch, tmp_path):
    saved: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        "mastodon_is_my_blog.account_config.get_accounts_config_path",
        lambda: tmp_path / "accounts.json",
    )
    monkeypatch.setattr(
        "mastodon_is_my_blog.account_config.set_credential",
        lambda name, field, value: saved.__setitem__((name, field), value) or True,
    )
    monkeypatch.setattr(
        "mastodon_is_my_blog.account_config.delete_credential",
        lambda name, field: saved.pop((name, field), None) is not None,
    )
    monkeypatch.setattr(
        "mastodon_is_my_blog.account_config.get_credential",
        lambda name, field: saved.get((name, field)),
    )
    return saved


def test_oob_login_never_asks_for_client_ids(monkeypatch, tmp_path, capsys) -> None:
    saved = isolate_config(monkeypatch, tmp_path)
    FakeMastodon.created_apps = []
    monkeypatch.setattr(auth_cli, "Mastodon", FakeMastodon)
    monkeypatch.setattr("builtins.input", lambda prompt="": "pasted-code")

    account_name = auth_cli.run_login("mistersql@mastodon.social", no_browser=True)

    assert account_name == "MISTERSQL"
    # Server inferred from the handle; app registered dynamically.
    assert FakeMastodon.created_apps[0]["api_base_url"] == "https://mastodon.social"
    accounts = load_configured_accounts()
    assert accounts[0].name == "MISTERSQL"
    assert accounts[0].base_url == "https://mastodon.social"
    assert saved[("MISTERSQL", "client_id")] == "generated-client-id"
    assert saved[("MISTERSQL", "access_token")] == "granted-access-token"
    out = capsys.readouterr().out
    assert "Client ID" not in out


def test_oob_login_duplicate_username_gets_unique_name(monkeypatch, tmp_path) -> None:
    isolate_config(monkeypatch, tmp_path)
    monkeypatch.setattr(auth_cli, "Mastodon", FakeMastodon)
    monkeypatch.setattr("builtins.input", lambda prompt="": "pasted-code")

    first = auth_cli.run_login("mistersql@mastodon.social", no_browser=True)
    second = auth_cli.run_login("mistersql@mastodon.social", no_browser=True)

    assert first == "MISTERSQL"
    assert second == "MISTERSQL_2"


def test_loopback_catcher_accepts_matching_state() -> None:
    port = auth_cli.pick_free_port()
    catcher = auth_cli.OAuthCodeCatcher(port, "expected-state")
    try:

        def hit():
            urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code=abc123&state=expected-state", timeout=5)

        thread = threading.Thread(target=hit)
        thread.start()
        code = auth_cli.wait_for_loopback_code(catcher, timeout=10)
        thread.join()
    finally:
        catcher.server_close()

    assert code == "abc123"


def test_loopback_catcher_rejects_state_mismatch() -> None:
    port = auth_cli.pick_free_port()
    catcher = auth_cli.OAuthCodeCatcher(port, "expected-state")
    try:

        def hit():
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code=abc123&state=evil", timeout=5)
            except urllib.error.HTTPError:
                pass  # 400 is the point

        thread = threading.Thread(target=hit)
        thread.start()
        code = auth_cli.wait_for_loopback_code(catcher, timeout=10)
        thread.join()
    finally:
        catcher.server_close()

    assert code is None
    assert catcher.error


def test_list_and_remove(monkeypatch, tmp_path, capsys) -> None:
    isolate_config(monkeypatch, tmp_path)
    monkeypatch.setattr(auth_cli, "Mastodon", FakeMastodon)
    monkeypatch.setattr("builtins.input", lambda prompt="": "pasted-code")
    auth_cli.run_login("mistersql@mastodon.social", no_browser=True)
    capsys.readouterr()

    assert auth_cli.run_list() == 0
    assert "MISTERSQL" in capsys.readouterr().out

    assert auth_cli.run_remove("mistersql") == 0
    assert load_configured_accounts() == []
    assert auth_cli.run_remove("mistersql") == 1


def test_auth_parser_wiring() -> None:
    from mastodon_is_my_blog.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["auth", "login", "user@example.social", "--no-browser"])
    assert args.command == "auth"
    assert args.auth_command == "login"
    assert args.account == "user@example.social"
    assert args.no_browser is True
    assert args.manual is False

    assert parser.parse_args(["auth", "list"]).auth_command == "list"
    assert parser.parse_args(["auth", "remove", "X"]).name == "X"
    assert parser.parse_args(["auth", "verify"]).name is None
