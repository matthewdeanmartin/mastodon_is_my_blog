# Clone and run locally

This is the most complete installation path because it gives you the backend, the frontend, and the static-export tooling in one checkout.

## Best for

Choose this path if you want:

- the full local app
- the least ambiguity
- the easiest way to follow this handbook exactly

## What you need

- **Git**
- **uv**
- **Node.js and npm**
- a **Mastodon account**

## 1. Clone the repository

```bash
git clone https://github.com/matthewmartin/mastodon_is_my_blog.git
cd mastodon_is_my_blog
```

## 2. Install Python dependencies

```bash
uv sync
```

## 3. Register an app on your Mastodon server

On your Mastodon server:

1. sign in
2. open **Settings**
3. open **Development**
4. create a new application
5. use `http://localhost:8000/auth/callback` as the redirect URL
6. grant `read` and `write` scopes

Save the **client ID** and **client secret**.

## 4. Run MIMB setup

```bash
uv run mastodon_is_my_blog init
```

You can add one account or several. If you do not have an access token yet, you can skip it and finish the browser login later.

## 5. Start the backend

```bash
uv run mastodon_is_my_blog start --reload --port 8000
```

## 6. Start the frontend

In a second terminal:

```bash
cd web
npm install
npm start
```

## 7. Open the app

Open:

```text
http://localhost:4200
```

If you skipped the access token during setup, connect through the app's login flow.

## Optional: build the static blog export

MIMB also includes a static blog export flow. That output goes into `docs/`, which is separate from this handbook.

```bash
npm --prefix docs-src install
npm --prefix docs-src run build
```
