"""OAuth-first CLI login: `mimb auth login user@server`.

Mirrors the web Connect Account flow (routes/admin.py start_identity_oauth +
main.py /auth/callback): dynamically registers an app on the user's server
with Mastodon.create_app, sends them to the authorize URL in a browser, and
exchanges the code — so nobody is ever asked to type a client ID.

Two ways the code comes back:
- loopback (default): a tiny stdlib HTTP server on 127.0.0.1:<free port>
  catches the redirect, checks state, and thanks the user.
- oob (--no-browser or when the loopback can't be used): the server shows
  the code and the user pastes it into the terminal.
"""

from __future__ import annotations

import secrets
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from mastodon import Mastodon

from mastodon_is_my_blog.account_config import (
    ConfiguredAccount,
    build_unique_account_name,
    delete_account_credentials,
    list_account_summaries,
    normalize_base_url,
    remove_configured_account,
    set_account_credentials,
    upsert_configured_account,
)
from mastodon_is_my_blog.credentials import get_credential

OOB_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"
SCOPES = ["read", "write"]
CLIENT_NAME = "mastodon_is_my_blog"
LOGIN_TIMEOUT_SECONDS = 300

LANDING_PAGE = b"""<!doctype html><html><head><meta charset="utf-8"><title>mimb</title></head>
<body style="font-family: sans-serif; max-width: 480px; margin: 4rem auto; text-align: center">
<h1>Connected!</h1><p>You can close this tab and return to the terminal.</p>
</body></html>"""


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class OAuthCodeCatcher(HTTPServer):
    """One-shot loopback server: stores the ?code= from the redirect if the
    state matches, then the caller shuts it down."""

    def __init__(self, port: int, expected_state: str):
        self.expected_state = expected_state
        self.code: str | None = None
        self.error: str | None = None
        super().__init__(("127.0.0.1", port), OAuthCallbackHandler)


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    server: OAuthCodeCatcher

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        query = parse_qs(urlparse(self.path).query)
        state_values = query.get("state")
        code_values = query.get("code")
        state = state_values[0] if state_values else None
        code = code_values[0] if code_values else None
        if state != self.server.expected_state or not code:
            self.server.error = "State mismatch or missing code in OAuth redirect."
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"OAuth state mismatch. Return to the terminal and try again.")
            return
        self.server.code = code
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(LANDING_PAGE)

    def log_message(self, *args):  # noqa: ARG002 - silence request logging
        pass


def wait_for_loopback_code(catcher: OAuthCodeCatcher, timeout: float) -> str | None:
    catcher.timeout = 1
    deadline = threading.Event()

    def alarm():
        deadline.set()

    timer = threading.Timer(timeout, alarm)
    timer.start()
    try:
        while catcher.code is None and catcher.error is None and not deadline.is_set():
            catcher.handle_request()
    finally:
        timer.cancel()
    return catcher.code


def resolve_server(handle_or_url: str | None) -> str:
    while True:
        raw = handle_or_url or input("Your Mastodon handle (user@server) or server URL: ")
        handle_or_url = None  # re-prompt on failure
        try:
            return normalize_base_url(raw)
        except ValueError as exc:
            print(exc)


def run_login(handle_or_url: str | None, *, name: str | None = None, no_browser: bool = False) -> str | None:
    """Full OAuth login. Returns the saved account name, or None on failure."""
    base_url = resolve_server(handle_or_url)
    allow_http = base_url.startswith("http://")

    print(f"Registering with {base_url} …")
    if no_browser:
        redirect_uri = OOB_REDIRECT_URI
        catcher = None
        state = None
    else:
        port = pick_free_port()
        redirect_uri = f"http://127.0.0.1:{port}/callback"
        state = secrets.token_urlsafe(32)
        catcher = OAuthCodeCatcher(port, state)

    client_id, client_secret = Mastodon.create_app(
        client_name=CLIENT_NAME,
        scopes=SCOPES,
        redirect_uris=redirect_uri,
        api_base_url=base_url,
    )
    m = Mastodon(api_base_url=base_url, client_id=client_id, client_secret=client_secret)
    authorize_url = m.auth_request_url(
        redirect_uris=redirect_uri,
        scopes=SCOPES,
        state=state,
        allow_http=allow_http,
    )

    if catcher is not None:
        print("Opening your browser to authorize. If nothing opens, visit:")
        print(f"  {authorize_url}")
        webbrowser.open(authorize_url)
        print("Waiting for you to authorize in the browser …")
        code = wait_for_loopback_code(catcher, LOGIN_TIMEOUT_SECONDS)
        catcher.server_close()
        if not code:
            print(catcher.error or "Timed out waiting for the browser authorization.")
            print("Tip: retry with `mimb auth login --no-browser` to paste the code by hand.")
            return None
    else:
        print("Open this URL in a browser, authorize, and paste the code below:")
        print(f"  {authorize_url}")
        code = input("Authorization code: ").strip()
        if not code:
            print("No code entered.")
            return None

    access_token = m.log_in(code=code, redirect_uri=redirect_uri, scopes=SCOPES, allow_http=allow_http)
    me = m.account_verify_credentials()

    existing_names = {summary.name for summary in list_account_summaries()}
    account_name = build_unique_account_name(name or me["username"], existing_names)
    upsert_configured_account(ConfiguredAccount(name=account_name, base_url=base_url))
    set_account_credentials(
        account_name,
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
    )
    print(f"Connected {me['acct']}@{base_url.split('://', 1)[1]} as account {account_name}.")
    return account_name


def run_list() -> int:
    summaries = list_account_summaries()
    if not summaries:
        print("No accounts configured. Run `mimb auth login your@handle` to add one.")
        return 0
    for summary in summaries:
        token_label = "token saved" if summary.has_access_token else "needs login"
        print(f"{summary.name}  {summary.base_url}  ({token_label})")
    return 0


def run_remove(name: str) -> int:
    names = {summary.name for summary in list_account_summaries()}
    if name.upper() not in names and name not in names:
        print(f"No account named {name}. Run `mimb auth list` to see accounts.")
        return 1
    remove_configured_account(name)
    delete_account_credentials(name)
    print(f"Removed {name}.")
    return 0


def run_verify(name: str | None = None) -> int:
    summaries = list_account_summaries()
    if name:
        summaries = [summary for summary in summaries if summary.name == name.upper() or summary.name == name]
        if not summaries:
            print(f"No account named {name}.")
            return 1
    if not summaries:
        print("No accounts configured.")
        return 1

    failures = 0
    for summary in summaries:
        access_token = get_credential(summary.name, "access_token")
        if not access_token:
            print(f"{summary.name}: no access token saved — run `mimb auth login`.")
            failures += 1
            continue
        try:
            m = Mastodon(api_base_url=summary.base_url, access_token=access_token)
            me = m.account_verify_credentials()
            print(f"{summary.name}: ok — {me['acct']} on {summary.base_url}")
        except Exception as exc:  # noqa: BLE001 - report any API failure per account
            print(f"{summary.name}: FAILED — {exc}")
            failures += 1
    return 1 if failures else 0
