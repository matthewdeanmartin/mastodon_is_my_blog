# Integration tests (mastodon_mock-backed)

These tests run the blog's real Mastodon client code against
[`mastodon_mock`](../../mastodon_mock) — an unpublished, **stateful** simulation
of a Mastodon server — instead of a live instance. No API keys are required.

What they prove:

- The blog's client factory (`mastodon_apis.masto_client.client` →
  `TimedMastodonClient`) talks to a real HTTP server correctly.
- The blog's catchup loop (`catchup.deep_fetch_user_timeline`) paginates against
  the `max_id` + Link-header contract the way it would against real Mastodon.
- `mastodon_mock` is genuinely stateful: a status POSTed shows up in the next
  GET of that account's timeline / `account_statuses`.

## How it works

`conftest.py` boots `mastodon_mock` as a uvicorn server on a free port
(session-scoped, in-memory SQLite, seeded with `alice` following `bob`) and
hands tests a client pointed at it. State accumulates within a session, which is
how the write round-trips are verified — so assertions key off `acct`/content,
not timeline ordering.

## Running

```bash
uv run pytest test_integration
# or
make test-integration
```

The whole package self-skips on Python < 3.13 or if `mastodon_mock` is not
installed (it is an editable path dependency on the sibling repo; see
`[tool.uv.sources]` in `pyproject.toml`). It is intentionally excluded from the
default `make test` / `pytest test` run.

## Once `mastodon_mock` is published

Replace the `[tool.uv.sources]` path entry with a normal version pin and drop
the editable dependency. The tests themselves should not need to change.
