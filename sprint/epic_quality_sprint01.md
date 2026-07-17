# Quality Epic — Sprint 01: Day-0 Experience, Tech Debt Inventory

## Why this epic exists

Three PyPI releases in a row produced a bad first-run experience on a clean
laptop: the app prompted for information it shouldn't need yet, or blew up
because it expected env vars that a brand-new install obviously doesn't have.
A new user may run **any** command first — `mimb start`, `mimb init`,
`mimb doctor`, `mimb admin sync` — and every one of them must behave sanely
on a machine with no `.env`, no keyring entries, no database, and possibly no
network. When something fails, the error must say what to do next, especially
when the cause is missing setup.

This sprint: fix the root causes of the day-0 failures, build a regression
net so a fourth bad release can't happen, and inventory the rest of the debt
for follow-on sprints.

---

## Findings inventory (audited 2026-07-17, commit a111cb6)

### A. Day-0 / onboarding — root causes (P0)

**A1. Engine and DB_URL are bound at import time — the single biggest WTF.**
`store.py:52-60`: `DB_BACKEND = resolve_backend()`, `DB_URL = get_default_db_url()`,
and `engine = create_async_engine(...)` all run at module import.
`cli.py:21-25` imports from `store` at module top. Consequences:

- **`mimb init` initializes the wrong database.** The wizard's
  `write_db_url_to_env()` (`cli.py:276`) sets `os.environ["DB_URL"]` *after*
  `store` was imported, so the engine is already bound to the old/default URL.
  `sync_identity_state()` → `init_db()` then creates schema in the database
  the user just chose to move away from. The choice only takes effect on the
  *next* process. This is exactly the "asked me stuff / blew up" class of bug.
- **Every CLI command pays for the engine.** Even `mimb --version` or
  `mimb auth list` imports `store`, resolves the backend, and constructs an
  engine. A malformed `DB_URL` in a stray `.env` crashes unrelated commands
  with a raw SQLAlchemy traceback instead of "your DB_URL in ./.env is
  invalid; run `mimb db-info`".
- **Import side effects:** `db_path.get_default_db_url()` does
  `data_dir.mkdir(parents=True)` (`db_path.py:86`) at import; `duck.py:25`
  copies `DB_URL` from `store` at import, so it too can go stale.

Fix: make engine/session lazy (cached factory function), have `cli.py` import
`store` inside the command handlers that need it, and re-resolve `DB_URL`
after the init wizard runs.

**A2. `mimb start` can crash on a fresh install with no network.**
`main.py:99` calls `duck.startup()` unguarded in lifespan. `duck.py:57` runs
`INSTALL sqlite;` which downloads the DuckDB extension from the internet on
first use. Fresh install + offline/firewalled machine → server fails to boot
with a DuckDB error. Contrast with the spaCy load right below it
(`main.py:102-112`) which is correctly wrapped in try/except and degrades.
Fix: same pattern — catch, log "analytics disabled", continue.

**A3. Config lives in `./.env` — silently lost when you `cd` elsewhere.**
`environment.py:8` does `load_dotenv()` from CWD, and the init wizard's
`write_db_url_to_env()` writes `./.env`. Run `mimb` from a different
directory and your DB choice silently reverts to the default SQLite path —
which *looks* like data loss to the user. The wizard prints a one-line
warning, but that's not enough. Fix: persist settings in a platformdirs
config file (`user_config_dir`) loaded regardless of CWD; keep `.env`/env
vars as overrides. This also stops the repo `.env` leaking `FRONTEND_URL` /
`APP_BASE_URL` into dev runs and tests.

**A4. Env vars read as import-time default parameters.**
`mastodon_apis/masto_client.py:29-32` — `def client(base_url=os.environ.get(...), ...)`.
Defaults are evaluated once at import, so anything that sets/loads env after
import (the init wizard, `load_dotenv` ordering, tests) is ignored. Move the
reads inside the function body.

**A5. No day-0 regression net.** Nothing in `test/` runs the CLI the way a
new user does: clean env, empty temp HOME/data dir, no keyring, no `.env`.
This is why the breakage shipped three times. See Sprint scope, task 1.

### B. Errors that don't advise the user

- Raw tracebacks from A1 (bad `DB_URL`) — no mention of `.env` or `mimb db-info`.
- `db_path.py:105` `get_sqlite_file_path` raises a decent message, but only
  the analytics layer sees it; if it escapes at startup (A2) the user gets a
  stack trace, not "analytics need SQLite; the app still works".
- `main.py /api/me` returns bare `401 Not connected` — the web UI should be
  told (and tell the user) to run `mimb auth login` or click Connect Account.
- Postgres unreachable at `mimb start` → asyncpg connection traceback. Should
  say: "Can't reach Postgres at <host>. Is it running? Check DB_URL / APP_PG_*;
  run `mimb doctor`."
- Good news: `mimb doctor` (`admin_cli.py:249-384`) is a solid model — every
  check has a `fix:` string. The bar for this epic: *any* setup-related
  failure anywhere should read like a doctor line.

### C. Comments/docs that no longer match the code

- `credentials.py:33-37` — docstring says "Returns True on success, False if
  keyring is unavailable"; the code never returns False, it raises
  `KeyringError`. Audit callers for the dead False-branch expectation.
- `pyproject.toml:185-186` — comment says "Assume Python 3.10", setting says
  `target-version = "py39"`, while `requires-python = ">=3.12"`. Ruff is
  linting for the wrong Python. Set `py312`, delete the comment.
- `store.py` module still owns models + engine + CRUD while a separate
  `models.py` exists — whichever is vestigial, the layout lies to readers.

### D. Dead code / repo clutter

- `Makefile1` is **git-tracked**. Delete or merge into `Makefile`.
- ~~`dev_database.py` has no importers~~ CORRECTED: it is alive — the
  Makefile invokes it via `python -m mastodon_is_my_blog.dev_database`.
  Keep it.
- Repo root is littered with unignored working files: `backup/`,
  `app_6_2026.db`, `app_bakcup7_2_2026.db` (note the typo), `mimb_server.db-shm/-wal`,
  `app.db-shm/-wal`. Extend `.gitignore` (`*.db-shm`, `*.db-wal`, `backup*/`,
  `app_*.db`) and move stray backups out of the tree.
- `Makefile` vs `tox.ini` vs `scripts/` — confirm one blessed task runner.

### E. Code smells / project-rule violations

- **60 underscore-prefixed functions across 16 files** despite the project
  CLAUDE.md ban on `_`-as-private (worst: `db_port.py` ×16,
  `link_previews.py` ×12, `duck.py` and `db_init.py` ×4 each; also
  `main.py` module globals `_root`, `_db_handler`). Mechanical rename sprint.
- `ruff` `line-length = 320` — effectively disables line-length linting and
  invites the 1,000-line-module style below.
- `duck.py` `FORUM_SUMMARY_CACHE` is an unbounded module-level dict (TTL
  checked on read, never evicted).

### F. Big balls of mud (split candidates)

| Module | Lines | Mixes together |
|---|---|---|
| `queries.py` | 1027 | sync jobs, read queries, API calls |
| `store.py` | 944 | engine/config, ORM models, CRUD, token logic |
| `routes/admin.py` | 903 | identity CRUD, OAuth, maintenance jobs, portal glue |
| `duck.py` | 817 | connection infra, caching, a pile of SQL strings |
| `routes/posts.py` | 729 | — |

### G. Missing unit-test coverage (no test file at all)

`admin_cli.py` (including **doctor** — the day-0 tool is itself untested),
`main.py` (lifespan, serve_spa path traversal guard), `credentials.py`,
`account_config.py`, `blogroll.py`, `blog_publish.py`, `bulk_sync_jobs.py`,
`maintenance.py`, `account_catchup_runner.py`, `schema_version.py`,
`db_path.py`, `db_log_handler.py`, `dialect_upsert.py`, `static_files.py`,
`routes/admin.py`, `routes/analytics.py`, `routes/observability.py`,
`routes/publish.py`. Also: `cli.py` has tests but not for the init wizard's
DB-selection path (which is where A1 bites).

### H. Performance (carry-over context)

`test_perf/` suites and `make perf-*` targets exist; the forum tab is the
known worst offender. Not this sprint's focus — folded into Sprint 03.

---

## Sprint 01 — SHIPPED (2026-07-17)

What actually landed (scope shifted once mid-sprint: the full lazy-engine
refactor was moved to Sprint 02 at the owner's request; the minimal
deferred-import fix below was enough to kill the wrong-database bug):

1. **Day-0 smoke suite** — `test/test_day_zero.py`, 12 tests, all passing in
   ~23s. Every top-level command runs in a real subprocess with a scrubbed
   environment, temp `MIMB_CONFIG_DIR`/`MIMB_DATA_DIR`, null keyring, and an
   empty CWD. Includes an isolation tripwire that fails any test whose output
   mentions the developer's real mimb data/config dirs.
2. **A1 minimal fix**: `cli.py` and `db_port.py` no longer import `store` at
   module top — `mimb init`'s DB choice now takes effect in the same process
   (verified end-to-end by `test_init_custom_sqlite_path_takes_effect_same_process`),
   and `mimb --version`/`auth list` never construct an engine. The engine is
   STILL built at `store` import time — that refactor is Sprint 02 task 1.
3. **A2**: `duck.startup()` guarded in the lifespan; analytics degrade with a
   warning instead of blocking boot.
4. **A3**: settings persist to `settings.env` in the per-user config dir
   (`environment.get_settings_env_path`); precedence shell > CWD `.env` >
   settings file; `mimb db-info` prints which source DB_URL came from.
5. **B**: engine-creation and DB-connect failures at the CLI print
   doctor-style advice; `db-info` exits 1 on an unreachable DB.
6. Hygiene: credentials docstring fixed, ruff `target-version = "py312"`,
   `Makefile1` deleted, `.gitignore` covers `*.db/-shm/-wal/backup*/app_*.db`
   (tracked `docs-src/app.db` explicitly excepted).

### Bugs DISCOVERED during the sprint (all fixed, none in the original audit)

- **`__main__.py` discarded exit codes** — `python -m mastodon_is_my_blog`
  always exited 0 regardless of command outcome.
- **Bare `dotenv.load_dotenv()` loaded the developer's repo `.env` into any
  process** — five call sites (`masto_client.py`, `masto_client_timed.py`,
  `queries.py`, `alembic/env.py`, `alembic_sync/env.py`). `find_dotenv`
  walks up from the *calling file's directory*, not the CWD, so the repo
  `.env` (real credentials!) leaked into supposedly-isolated test
  subprocesses and would leak into any pip install that has a `.env`
  anywhere above site-packages. The alembic one was the nastiest: it
  injected credentials mid-run during `ensure_schema_stamped`, after all
  well-behaved loading was done. All five now use `load_environment()`.
- **`get_schema_version` swallowed connection failures** — an unreachable
  Postgres was reported as healthy-but-unversioned.
- **platformdirs ignores HOME/LOCALAPPDATA env overrides on Windows** (it
  asks the OS) — added `MIMB_DATA_DIR`/`MIMB_CONFIG_DIR` as first-class
  overrides, honored by the app, the uninstaller, and the test suite.

### Known issues found but NOT fixed (queued for Sprint 02)

- **Identity mirror-delete can violate FKs / is dangerous**:
  `sync_configured_identities` (`store.py:739-741`) deletes any identity
  whose `config_name` is missing from the current config. Two problems:
  (a) deleting an identity that still has `cached_accounts` rows raises
  `ForeignKeyViolationError` on Postgres (observed live with identity id=5,
  KATHERINE — so `mimb auth remove` is broken there today); (b) an *empty*
  config (fresh shell, lost accounts.json) against a full DB would attempt
  to delete every identity. Needs cleanup-or-detach semantics plus a "config
  empty but DB populated — refusing to mirror-delete" guard.
- Verify the built wheel actually ships `alembic.ini` + `alembic/`
  (`db_init._alembic_config` resolves them relative to the package parent);
  add a wheel-install smoke run to CI.

Verification: `uv run python -m pytest test/` → 479 passed.
`uv run ruff check` → clean.

## Original Sprint 01 scope (for reference; see SHIPPED above)

1. **Day-0 smoke test suite** — `test/test_day_zero.py`. For each top-level
   command (`start` via TestClient/lifespan, `init` with scripted stdin,
   `doctor`, `db-info`, `auth list`, `admin sync`, `publish`, `version`,
   bare `mimb`): run with a scrubbed environment (no `DB_URL`, no
   `MASTODON_*`, no `FRONTEND_URL`/`APP_BASE_URL`, temp platformdirs home,
   keyring mocked absent, CWD = empty temp dir). Assert: no traceback, exit
   code sane, and any failure message contains actionable advice. Use
   `monkeypatch.setenv` (never `delenv`-and-hope — the repo `.env` leak).
   *This lands first so every later fix is provable.*
2. **Lazy engine (A1).** `store.py` engine/session become cached factories;
   `cli.py` defers store imports into handlers; init wizard re-resolves after
   writing `DB_URL`; verify `mimb init` → choose Postgres → schema lands in
   Postgres in the same process.
3. **Guard `duck.startup()` (A2)** with try/except + "analytics disabled"
   log, mirroring the spaCy block.
4. **Config file out of CWD (A3)** — platformdirs config, `.env` demoted to
   override; `mimb db-info` reports which source won.
5. **Error-message pass (B)** — wrap DB connect/URL-parse failures at CLI and
   lifespan entry points with doctor-style "what happened / what to do" text.
6. **Quick hygiene:** fix `credentials.py` docstring, fix ruff
   `target-version`, delete `Makefile1`, extend `.gitignore` for db/backup
   clutter, verify-and-delete `dev_database.py`.

**Acceptance:** fresh `pipx install` on a clean VM (or simulated via the
smoke suite): `mimb start` boots and serves the UI with zero env vars set,
offline; `mimb init` honors the DB choice immediately; every deliberate
misconfiguration tried produces advice, not a traceback.

**Verification commands:** `uv run python -m pytest test/ -x`, then the new
`uv run python -m pytest test/test_day_zero.py -v`; manual: `uv build` +
install the wheel into a throwaway venv with `HOME`/`LOCALAPPDATA` pointed
at a temp dir, run each command.

---

## Next sprint (handoff to the next bot — read this first)

**Quality Epic — Sprint 02: Lazy engine, identity-delete safety, test-gap
closure.**

Prereq: Sprint 01 merged (it is — see SHIPPED above); day-0 smoke suite
green (`uv run python -m pytest test/test_day_zero.py`, ~23s — if it
suddenly takes minutes, credentials are leaking and real API calls are
happening: STOP and find the leak; see the dotenv findings above).

1. **Lazy engine loading (moved here from Sprint 01 at the owner's
   request).** `store.py` still runs `resolve_backend()` +
   `get_default_db_url()` + `create_async_engine()` at import. Replace the
   module-level `engine`/`async_session`/`DB_URL`/`DB_BACKEND` globals with
   cached factory functions (`get_engine()`, `get_session_factory()`, …)
   that re-read the environment on first use, with an explicit
   `reset_engine()` for tests and the init wizard. Callers to migrate:
   `schema_version.py`, `db_init.py`, `duck.py` (imports `DB_URL` at module
   top — goes stale), `admin_cli.py`, `dev_database.py`, and
   `test/conftest.py` (its "set DB_URL before store import" dance at the top
   becomes unnecessary — simplify it). Then the deferred imports added to
   `cli.py` in Sprint 01 can stay or be simplified; the SystemExit wrapper
   around engine creation in `store.py` moves into the factory.
2. **Fix identity mirror-delete** (see Known issues in Sprint 01): make
   `sync_configured_identities`/`mimb auth remove` delete or detach the
   dependent `cached_accounts`/cached data rows (decide: cascade delete vs
   orphan cleanup job), and refuse to mass-delete identities when the config
   is empty but the DB is populated — print advice instead. Add a Postgres
   integration test for remove-with-cached-data (the FK failure only
   reproduces on a backend that enforces FKs — live-observed on Postgres).
3. **Tests for the day-0 tooling itself:** `admin_cli.py` doctor (each check
   forced ok/warn/FAIL via mocks), `cli.py` init wizard (DB selection,
   account prompts, re-entry with existing accounts), `credentials.py`
   keyring-present/absent/raising matrix.
4. **Split `store.py` (944 lines):** engine/session config → `db_engine.py`
   (the lazy factories from task 1 give a natural seam); ORM models
   reconciled with the existing `models.py`; CRUD stays. No behavior change;
   the whole existing suite is the regression net.
5. **Wheel-install smoke:** build the wheel, install into a throwaway venv,
   run the day-0 suite against that install (swap `PYTHONPATH` for the
   installed package). This is the only thing that catches
   packaging-manifest gaps like `alembic/` not shipping.
6. If time remains: split `queries.py` (1027 lines) into sync jobs vs read
   queries; route tests for `routes/admin.py`; start the underscore-prefix
   rename in modules you already touched — never as a drive-by in unrelated
   files.

Sprint 03 candidates (write up properly at Sprint 02 close): forum-tab
performance (use `test_perf/` + `make perf-*` baselines, `DB_URL` not
`DB_BACKEND` for backend selection in perf runs), finish the underscore
rename, split `routes/admin.py` and `duck.py`, bound `FORUM_SUMMARY_CACHE`.

Conventions for this epic: docs live at `sprint/epic_quality_sprintNN.md`;
every sprint ends by writing the next sprint's handoff into its doc; run
tests with `uv run python -m pytest`; never `delenv` repo-`.env`-leaked vars
in tests — `setenv` them explicitly.
