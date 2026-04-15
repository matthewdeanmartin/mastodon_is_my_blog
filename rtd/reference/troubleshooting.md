# Troubleshooting

If Mastodon is My Blog (MIMB) feels confusing at first, the problem is usually one of four things: connection, identity selection, cache freshness, or expectations.

## The browser says it cannot reach the server

Check that both parts are running:

```bash
uv run mastodon_is_my_blog start --reload
```

and

```bash
cd web
npm start
```

## Login or OAuth is not finishing

Double-check the Mastodon app registration:

- redirect URL must be `http://localhost:8000/auth/callback`
- scopes should include `read` and `write`
- client ID and client secret must match what you entered during `init`

## I opened the app and nothing is there

Check these in order:

1. choose the right **Meta Account ID**
2. choose the right **identity** at the top of the app
3. open **Admin**
4. run **Force Refresh Cache**

## A person is missing from People

Possible reasons:

- you are in the wrong identity context
- that account is filtered out by the current blog roll filter
- the local cache has not been refreshed recently

## Content is empty

For the Content page, check whether you are using:

- **From My Follows**, which depends on your current identity's cached network
- **Hashtag Groups**, which depend on bundles or synced server follows

If needed:

1. open **Admin**
2. use **Sync Server Follows**
3. or create a new bundle

## The Write page is too simple for my workflow

That is real, not user error. The current editor is intentionally lightweight, and the roadmap already calls for a better one.

## Some filters feel rough

That is also real. MIMB's filters are one of its most important ideas, and they are still being improved.

Use the current filters as helpful reading lenses, not as perfect truth machines.
