# Sprint 02 — `mimb auth`: OAuth-first CLI login

Status: done

## Problem

The only CLI way to add an account is `mimb init`, which demands client
ID/secret — credentials users don't have. The web flow already does dynamic
app registration (`Mastodon.create_app`) + OAuth; the CLI should too.

## Scope

New module `mastodon_is_my_blog/auth_cli.py` + `auth` subcommands in `cli.py`:

- `mimb auth login [user@server | server]`
  1. Infers the server (`normalize_base_url` handles handles/bare domains).
  2. `Mastodon.create_app` on that server (scopes read+write) — no typed IDs.
  3. Opens the browser to the authorize URL. Default: loopback redirect
     (`http://127.0.0.1:<free-port>/callback`, tiny stdlib HTTP catcher with
     a state check). `--no-browser` (or headless): out-of-band
     (`urn:ietf:wg:oauth:2.0:oob`) — print URL, paste the code.
  4. Exchanges the code, verifies credentials, saves account
     (name defaults to the Mastodon username; `--name` overrides;
     `build_unique_account_name` avoids collisions), then runs the same
     identity sync `init` did.
  - `--manual` = the old client-ID/secret/token prompts
    (`save_account_interactively`), for mock servers / headless / power use.
- `mimb auth list` — configured accounts + token state.
- `mimb auth remove <name>` — config + keyring cleanup.
- `mimb auth verify [name]` — calls `account_verify_credentials` per account,
  prints ok/failure.

Flow mirrors `routes/admin.py:start_identity_oauth` + `main.py:/auth/callback`
(create_app → auth_request_url(state=…, allow_http for http:// dev servers) →
log_in(code=…)).

## Tests

- Parser wiring for all four subcommands.
- `auth login` oob path end-to-end with a faked Mastodon class
  (create_app/auth_request_url/log_in/account_verify_credentials), config
  path redirected to tmp_path, credentials monkeypatched to a dict.
- Loopback catcher: request with the right state yields the code; wrong
  state rejected.

## Result

- `mastodon_is_my_blog/auth_cli.py`: `run_login` (loopback + oob),
  `OAuthCodeCatcher` (state-checked one-shot HTTP server), `run_list`,
  `run_remove`, `run_verify`.
- `cli.py`: `auth` subparser + `run_auth_command`; `--manual` reuses
  `save_account_interactively`; successful login runs `sync_identity_state()`.
- `test/test_auth_cli.py`: oob login end-to-end with FakeMastodon (asserts no
  client-ID prompt, unique-name collision handling), loopback state
  accept/reject, list/remove, parser wiring. 20 passed with test_cli.
