# AGENTS.md — Notes for AI assistants working in this repo

This file is for agents (Claude, Codex, etc.). For humans, see `README.md`.

Subdirectory-specific guidance:
- Python backend: `mastodon_is_my_blog/AGENT.md`
- Angular frontend: `web/AGENTS.md`
- Repo-wide rules: `CLAUDE.md`

## Looking up bugs the user has encountered locally

The app captures all `WARNING`/`ERROR`/`CRITICAL` log records into the SQLite
`error_log` table via `db_log_handler.DbLogHandler`. There are three ways to
reach those records — from cheapest to most powerful:

1. **CLI / quick HTTP read** while the dev server is running:

   ```powershell
   curl http://localhost:8000/api/admin/error-log?limit=200
   ```

   This returns the most recent rows as JSON, with fields `id`, `ts`, `iso`,
   `level`, `logger`, `message`, `exc_text`. Tracebacks live in `exc_text`.

2. **Direct SQLite read** when the server isn't running. The DB path is
   resolved by `mastodon_is_my_blog.db_path.get_sqlite_file_path()` — typically
   `%LOCALAPPDATA%\mastodon_is_my_blog\app.db` on Windows, or wherever
   `DB_URL` points. Example:

   ```powershell
   uv run python -c "import sqlite3; from mastodon_is_my_blog.db_path import get_sqlite_file_path; con = sqlite3.connect(get_sqlite_file_path()); [print(r) for r in con.execute('SELECT datetime(ts, ''unixepoch''), level, logger_name, message, substr(exc_text, 1, 400) FROM error_log ORDER BY ts DESC LIMIT 50')]"
   ```

3. **Admin UI**: the "Error Log" panel on the `/admin` route (`✏️ Write` in
   the nav) calls the same endpoint. This is what the user is referring to
   when they mention the "error log UI built into it".

Retention: 30 days, enforced by `db_log_handler.purge_old_rows`.

When the user says "I ran into bugs", default to (1) or (2) before asking
them to copy/paste a traceback.

## Adding new error capture

`db_log_handler.DbLogHandler` is a stdlib `logging.Handler`, so anything that
goes through `logger.exception(...)` / `logger.error(...)` / `logger.warning(...)`
in any module will be captured automatically — no per-call wiring needed.

If you find an exception path that is currently swallowed (e.g. `except
Exception: pass`), prefer letting it raise (see `AGENT.md`'s "Error
'Handling'" section) or, if it must be swallowed, log it with
`logger.exception("...")` so it lands in the error log.
