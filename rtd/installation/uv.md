# Install with uv

This is the most natural path if you already use `uv` for Python tools and virtual environments.

## When to choose this path

Choose `uv` if you want:

- fast Python dependency setup
- an easy way to run the project without managing `pip` manually
- a workflow that matches the repository's own setup

## Before you begin

You will need:

- **uv**
- **Python 3.12 or newer**
- **Node.js and npm**
- a **Mastodon account**

## Option 1: run from a cloned checkout

```bash
git clone https://github.com/matthewmartin/mastodon_is_my_blog.git
cd mastodon_is_my_blog
uv sync
```

Then initialize your account:

```bash
uv run mastodon_is_my_blog init
```

Start the backend:

```bash
uv run mastodon_is_my_blog start --reload
```

Start the frontend in another terminal:

```bash
cd web
npm install
npm start
```

## Option 2: install the command as a uv-managed tool

If you prefer a tool-style install:

```bash
uv tool install --from git+https://github.com/matthewmartin/mastodon_is_my_blog.git mastodon_is_my_blog
```

Then run:

```bash
mastodon_is_my_blog init
mastodon_is_my_blog start --reload
```

You will still want a repository checkout for the browser frontend.

## Why many users will prefer this route

The repository already assumes `uv` for Python work, so this path tends to be the least surprising.
