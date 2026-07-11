# Ensuring MIMB stays fast

MIMB's recurring performance problem is SQL: a feed, counts panel, or forum
page that was instant on a week-old database becomes sluggish once the cache
holds a year of posts. This page describes how we measure performance, how we
catch regressions, and what users and contributors can do about slowness.

## The strategy in one paragraph

Performance is checked at two speeds. **Every CI build** runs a short,
budget-based smoke suite against the `mastodon_mock` server and an in-memory
database; it only fails on order-of-magnitude regressions (an accidental
O(n²) loop, per-row commits, an N+1 query), never on 5–10% machine noise.
**At major releases**, a full benchmark suite runs locally against a
realistic ~1 GB database — once per supported configuration
(sqlite+duckdb and postgres+duckdb) — and compares against a baseline saved
on the same machine, failing only when a query's median time regresses by
more than 40%. Big-DB benchmarks are deliberately *not* run on every build:
they take minutes, need a seeded database, and their numbers are only
meaningful compared against a baseline from the same machine.

## The three performance surfaces

| Surface | What runs it | Where it's benchmarked |
| --- | --- | --- |
| SQLAlchemy hot paths (feed pages, counts panel, unread badge, ingest upserts) | sqlite/aiosqlite or postgres/asyncpg | `test_perf/test_perf_sqlalchemy.py` |
| DuckDB analytics (forum threads, hashtags, heatmaps, notification trends) | DuckDB attaching the app DB read-only | `test_perf/test_perf_duckdb.py` |
| Everything else (HTTP client, status parsing, payload building) | `mastodon_mock` over real HTTP | `test_perf/test_perf_mock_smoke.py` |

The **forum tab is historically the worst performer** and gets extra
coverage: the raw `forum_thread_summaries` DuckDB aggregation with a cold
cache, the warm-cache path (a regression there means the 30-second result
cache broke), the `forum_friend_reply_counts` scan, and the *entire*
`/api/forum/threads` endpoint — following-accounts fetch, DuckDB scan with
friend counting, then Python-side faceting and sorting over every thread.
When the forum regresses, the split benchmarks tell you which layer is
guilty. (This coverage found its first regression pre-emptively: friend
counting via `author_acct IN (1,500 placeholders)` inside the aggregate cost
~17s per request at 1M posts; it is now a hash join against a VALUES
relation. If you touch that query, keep the join — do not reintroduce an
IN list.)

Turso is not benchmarked: DuckDB analytics are disabled on that backend, and
its SQL performance is dominated by network latency to the Turso service,
which a local benchmark cannot measure meaningfully.

## Running the benchmarks (contributors, at release time)

Everything lives in `test_perf/`, which is never collected by the normal
`make test` / `pytest test` runs. The big-DB suites additionally require
`MIMB_PERF=1`, so nothing slow can run by accident.

### 1. Seed the perf database (once per machine)

```bash
make perf-seed                # ~1 GB sqlite db in perf/mimb_perf.db, a few minutes
make perf-seed-postgres       # same data into $(PERF_POSTGRES_URL)
                              # default: postgresql://postgres:xyzzy@localhost:5432/mimb_perf
```

The seeder (`test_perf/seed_perf_db.py`) writes through the app's own
SQLAlchemy engine, so one script fills either backend. The data is shaped
like a long-running install: ~1.2M posts over 18 months (denser recently),
25% of them replies threaded under roots so the forum has real threads,
zipf-distributed hashtags, content flags, notifications concentrated in the
last 90 days, seen-post rows, and an API call log. It is deterministic
(seeded RNG), and it refuses to write into a non-empty database, so it can
never touch your real `app.db`.

For the postgres target, create the database first
(`CREATE DATABASE mimb_perf`) — the seeder creates tables, not databases.

You can also point the suite at a *real* database copy instead of a seeded
one: set `DB_URL` to it and, if your data isn't under meta account 1 /
identity 1, set `MIMB_PERF_META_ID` / `MIMB_PERF_IDENTITY_ID`.

### 2. Save a baseline (once per machine, and after intentional changes)

```bash
make perf-baseline-sqlite
make perf-baseline-postgres
```

This runs all benchmarks with `pytest-benchmark` and saves the numbers under
`.benchmarks/` (gitignored — baselines are only comparable on the machine
that produced them, so they are never committed or shared).

### 3. Check before a major release

```bash
make perf-check-sqlite
make perf-check-postgres
```

Each re-runs the suite and compares against the most recent saved baseline
for that backend, failing if any benchmark's **median regresses more than
40%** (`PERF_FAIL_THRESHOLD=median:40%`, overridable). The threshold is
deliberately loose: run-to-run noise on a desktop is typically under 15%,
and the point is to catch "the forum got 3x slower", not to litigate 8%.

After an *intentional* change (a new column in a hot query, a heavier
aggregation you accepted on purpose), re-run `make perf-baseline-*` to make
the new numbers the reference.

### The CI smoke suite

`make perf-smoke` (also a step in the build workflow) runs three checks in
~20 seconds: paginate 120 statuses out of `mastodon_mock` over HTTP and
upsert them; bulk-upsert a 1,000-status batch; run a first feed page over a
few thousand rows. Each asserts a wall-clock budget roughly 10x what a slow
CI runner needs, so they fail only on structural regressions. If perf-smoke
fails in CI, something is genuinely broken — do not fix it by raising the
budget without understanding why.

## Advice for contributors

- **Touching a query in `queries.py`, `routes/`, or `duck.py`?** Run the
  relevant `make perf-check-*` against your seeded DB before and after. The
  benchmarks call the real functions (e.g. `get_counts_optimized`,
  `bulk_upsert_posts`, `duck.forum_thread_summaries`, the whole forum
  endpoint), so your change is measured as production runs it.
- **Adding a filter or sort?** Check it can use an existing index on
  `cached_posts` (they are all composite, starting with `meta_account_id`).
  A new query shape without index support will look fine in unit tests with
  40 rows and fall over at 1M.
- **Adding an analytics feature?** Prefer a DuckDB query in `duck.py` over a
  Python loop across rows, and add a benchmark for it in
  `test_perf/test_perf_duckdb.py` — a copy of an existing test is enough.
- **Never make the fast suite slow.** Anything needing a big database goes
  in `test_perf/` behind `MIMB_PERF=1`, not in `test/`.
- Slow DuckDB queries (>0.5s) are logged at WARNING by `duck.run` — check
  the error log when investigating user reports.

## Advice for users

If MIMB feels slow with a large cache:

- **Prefer Postgres for big installs.** Local SQLite serializes writes; a
  sync running in the background can make reads stall. `make dev` runs on
  Postgres by default.
- The **forum tab** is the most expensive view. Its results are cached for
  30 seconds — the first load after a sync is the slow one. If it is always
  slow, your database may have an enormous number of small threads; consider
  pruning old posts.
- **Regex search** (`content_regex_search`) scans every post's content by
  design. On a 1M-post database expect it to take a second or more; that is
  a table scan, not a bug.
- Keep an eye on database size (Admin → status). A multi-year cache can be
  exported and pruned; smaller databases are faster on every path.
