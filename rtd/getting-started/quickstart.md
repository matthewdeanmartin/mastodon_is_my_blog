# Quickstart

This quickstart assumes you want the full local app experience.

## Step 1: install and start the app

From the repository root:

```bash
uv sync
uv run mastodon_is_my_blog init
uv run mastodon_is_my_blog start --reload
```

In another terminal:

```bash
cd web
npm install
npm start
```

Open `http://localhost:4200`.

## Step 2: pick your local person record

The login page asks for a **Meta Account ID**.

For a simple local setup, `1` is usually the default.

Think of this as **you, the person using the app locally**, not one specific Mastodon identity.

## Step 3: choose your current Mastodon identity

At the top of the app, choose the identity you want to browse as.

This matters because MIMB is context-aware:

- your follows differ by identity
- your content bundles differ by identity
- your cached reading view differs by identity

## Step 4: connect to Mastodon if needed

If the Admin page says you are not connected:

1. open **Admin**
2. choose **Connect Account**
3. approve the app on your Mastodon server

## Step 5: refresh the cache

Still in **Admin**, use **Force Refresh Cache**.

This pulls in:

- who you follow
- who follows you back
- recent activity from your timeline
- recent notifications
- your own recent posts

## Step 6: start reading

Go to **People** and begin with:

- **My Blog** for your own writing
- **Everyone's Blog** for a wider combined view
- **Top Friends** or **Mutuals** for more focused reading

## Step 7: learn the main filters

The default view is usually **Storms**, which highlights long posts and self-threaded writing.

Then try:

- **Shorts** for short standalone posts
- **Questions** for posts that invite replies
- **Links** for posts with links
- **Pictures** and **Videos** for media-heavy reading

## Step 8: build topic views

Open **Admin** and create a **Content Hub Bundle**. Add:

- hashtags for exact tag-based collections
- search terms for broader server-side discovery

Then open **Content** to browse the result.
