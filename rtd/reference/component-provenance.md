# Component provenance

Supply chains matter. Mastodon is My Blog (MIMB) is not one monolithic thing; it is a stack of components from different places.

This page explains where the major pieces come from so you know what you are trusting.

## The main components

| Component | Source | Role |
| --- | --- | --- |
| Your Mastodon account and social graph | Your Mastodon server | The source of truth for identity, posts, follows, and permissions. |
| Mastodon API access | The Mastodon app you register on your server | Lets MIMB read and publish on your behalf. |
| MIMB backend | This repository's Python package | Syncs data, stores the local cache, and serves the API used by the web app. |
| Local cache | SQLite on your machine | Stores the material MIMB uses for its filtered views. |
| Web interface | This repository's Angular app in `web/` | The browser experience for People, Content, Forum, Write, and Admin. |
| Credential storage | Your operating system keyring | Stores sensitive account secrets when available. |
| Static blog export | This repository's Eleventy tooling in `docs-src/` | Builds a publishable blog-style output of your own posts. |
| User handbook | MkDocs and Read the Docs config in this repository | Publishes the documentation you are reading now. |

## Why this matters

When you install MIMB, you are trusting more than one ecosystem:

- Python packages for the backend
- Node packages for the frontend
- your Mastodon server's OAuth and API behavior
- local OS facilities such as keyring and file storage

## What you can review yourself

If you care about provenance, start with:

- `pyproject.toml` for Python dependencies
- `uv.lock` for the Python dependency resolution used by the repository
- `web/package.json` for frontend dependencies
- `.github/workflows/` for automation that builds or publishes parts of the project

## A practical trust model

For many people, the right question is not:

> "Is this stack dependency-free?"

It is:

> "Can I see what the moving parts are, and do I control where it runs?"

MIMB scores well on that second question because it is meant to run locally and its major parts are visible in the repository.

## Best practice if supply chain risk matters to you

- prefer reviewing the repository before installing
- prefer tagged or otherwise intentional releases over random snapshots
- keep your operating system, Python tools, and Node tools updated
- treat dependency changes as worth reviewing, especially before public deployment
