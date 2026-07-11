# Sprint 03 — `mimb init` becomes a real setup wizard

Status: done

## Problem

`init` only interrogated for account credentials (now `auth login --manual`'s
job) and never asked the one thing a fresh install actually decides: where the
database lives. It also had change/delete account loops that duplicate what
`mimb auth` now does better.

## Scope

Rework `run_init_command()` in `cli.py`:

1. **Database step** — shows the currently resolved URL
   (`db_path.get_default_db_url()`); offers to change it:
   - SQLite: accept default path or enter a custom file path.
   - Postgres: paste a `postgresql://…` URL (normalized to `+asyncpg`).
   Writes `DB_URL` into `./.env` via `dotenv.set_key` (main.py already
   `load_dotenv()`s) and exports it for the rest of the wizard. Prints a
   reminder that `.env` is cwd-relative.
2. **Account step** — zero accounts: "Connect a Mastodon account now?"
   → `auth_cli.run_login` (browser OAuth, no client IDs). Existing accounts:
   list them and point at `mimb auth …` instead of the old change/delete
   prompt loops (removed, along with `choose_account`).
3. **Finish** — runs the existing `sync_identity_state()` (init_db + schema
   stamp + default meta account + identity sync) and prints `mimb start`
   next-steps.

`save_account_interactively` stays (backs `mimb auth login --manual`).

## Tests

`test_cli.py` additions: wizard with no accounts prompts db + connect and
calls auth login; wizard with accounts lists them and doesn't prompt for
credentials; `.env` gets DB_URL written on a postgres choice.

## Result

- `run_init_command` rebuilt as described: database step (sqlite custom path
  or postgres URL → `.env` DB_URL via `dotenv.set_key`, also exported to the
  process), account step delegates to `auth_cli.run_login`, existing accounts
  just listed with a pointer to `mimb auth`.
- Removed `choose_account` + the change/delete prompt loops (superseded by
  `mimb auth remove` / `auth login --manual`).
- New helpers: `normalize_postgres_url`, `write_db_url_to_env`,
  `prompt_database_setup`.
- Tests: init-with-accounts never mentions Client ID; init-without-accounts
  calls OAuth login; postgres URL normalization; .env writing. 27 passed
  (test_cli + test_auth_cli), ruff clean.
