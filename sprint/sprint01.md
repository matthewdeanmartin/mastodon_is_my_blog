# Sprint 01 — First-run fixes (stop interrogating new users)

Status: done

## Problem

`pipx install mastodon-is-my-blog` → `mimb start` on a clean machine forcibly
runs the credential wizard (`cli.main()` gate on `has_configured_identities()`),
which asks for client ID/secret — things a first-time user cannot know. The web
UI already onboards fine from a zero-account state via Connect Account OAuth.
Also: `mimb --version` errors (only the `version` subcommand exists), help text
says `mastodon_is_my_blog` instead of `mimb`, and the instance-URL prompt
rejects `mastodon.social` and `user@server` instead of inferring `https://…`.

## Scope

1. Remove the forced-init gate in `cli.main()`. `mimb start` with no accounts
   just starts and prints: connect via the web UI at the printed URL.
2. `--version` flag (argparse `action="version"`); keep `version` subcommand.
3. `prog="mimb"` in the parser.
4. Forgiving `normalize_base_url` in `account_config.py`: accepts
   `https://server`, `server`, `user@server`, `@user@server` → `https://server`.
   Empty/garbage still raises `ValueError`.
5. Update `test/test_cli.py` (first test asserted the old forced-init
   behavior) + new tests for `--version` and URL normalization.

## Out of scope (later sprints)

- Sprint 02: `mimb auth` group — OAuth-first login (dynamic app registration,
  browser flow), list/remove/verify, `--manual` for today's raw prompts.
- Sprint 03: `init` rework — asks db backend (sqlite/postgres → .env DB_URL),
  delegates account connect to `auth login`, never asks client ID.
- Sprint 04: `mimb admin` group (sync/catchup/rebin/backfills), `mimb publish`
  (wraps blog_publish.py), `mimb doctor`.

## Result

- `cli.main()` no longer runs `run_init_command()` for unconfigured installs;
  `start_server()` prints a "connect in the web UI" hint instead.
- `--version` flag added (`version` subcommand kept); parser `prog="mimb"`.
- `normalize_base_url` now infers `https://server` from bare domains and
  fediverse handles; rejects empty/no-host/non-http schemes.
- Tests: `test/test_cli.py` rewritten (old test asserted forced init);
  34 passed across cli/settings_loader/connect/store suites.
