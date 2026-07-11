# Sprint 04 — `mimb admin`, `mimb publish`, `mimb doctor`

Status: done

## Problem

Every maintenance action (sync, catch-up, rebin, backfills) requires the web
UI; publishing requires make targets. Super-advanced/headless users want these
from the CLI without a running server.

## Scope

1. **`mastodon_is_my_blog/maintenance.py`** — extract route-inline logic so
   CLI and API share one implementation:
   - `backfill_content_flags_for_identity(meta_id, identity_id)` (moved from
     routes/admin.py backfill-content-flags body).
   - `run_nlp_backfill(meta_id, nlp, on_progress, cancelled)` (moved from the
     nlp-backfill/start runner body).
   Routes delegate; behavior unchanged.
2. **`mastodon_is_my_blog/admin_cli.py`** — local-mode CLI context
   (default meta account + first/named identity), then thin async wrappers:
   - `admin sync [--no-force]` → `sync_all_identities`
   - `admin download-friends` → `sync_all_following_for_identity` (prints progress)
   - `admin download-notifications` → `sync_all_notifications_for_identity`
   - `admin favourites [--full]` → `sync_my_favourites_for_identity`
   - `admin rebin` → `recompute_account_post_stats`
   - `admin backfill-flags` → maintenance module
   - `admin nlp-backfill` → loads spaCy itself, maintenance module
   - `admin catchup [--mode urgent|trickle] [--max-accounts N]` →
     `catchup_runner.start_job`, awaits the task with progress prints
3. **`mimb publish [--build-only] [--pages-workflow] [-m MSG]`** — wraps
   blog_publish.py (Sprint of 2026-07-11: build to ./docs, workflow, git push).
4. **`mimb doctor`** — environment checks: DB reachable + schema, accounts +
   keyring, node/npm/eleventy/git, spaCy model. Exit 1 if anything critical
   fails.

## Tests

Parser wiring for admin/publish/doctor; doctor with mocked checks; existing
route tests guard the maintenance.py extraction; full backend suite at end.

## Result

- `maintenance.py` extracted; routes/admin.py backfill-content-flags and
  nlp-backfill/start now delegate (route tests unchanged and passing).
- `admin_cli.py`: `get_context` (init_db + stamp + default meta + identity
  by --account or first), all eight admin subcommands, `run_publish`
  (build → optional workflow → commit/push via blog_publish), `run_doctor_command`.
- `cli.py`: `admin`/`publish`/`doctor` subparsers + dispatch; admin commands
  refuse server mode.
- Verified: full backend suite 440 passed; `mimb doctor` live run all-ok
  (db schema 016, keyring account, git/node/npm/eleventy/spacy found);
  bare `mimb admin` / `mimb auth` print usage and exit 2.
