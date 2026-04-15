# Mastodon is My Blog - Setup Guide

## Prerequisites
- Python 3.12+
- Node.js and npm (for Angular frontend)
- A Mastodon account

## Step 1: Register Your Application on Mastodon

1. Log into your Mastodon instance (e.g., mastodon.social)
2. Go to Settings → Development → New Application
3. Fill in the details:
   - **Application name**: My Blog Console
   - **Redirect URI**: `http://localhost:8000/auth/callback`
   - **Scopes**: Select `read` and `write`
4. Click "Submit"
5. Copy your **Client key** (client ID) and **Client secret**

## Step 2: Configure the CLI and backend

1. Install Python dependencies:
   ```bash
   uv sync
   ```

2. Run the interactive setup:
   ```bash
   uv run mastodon_is_my_blog init
   ```

3. Follow the prompts:
   - Give the account a short name.
   - Enter the Mastodon instance URL.
   - Enter the client ID and client secret from step 1.
   - Optionally enter an access token now, or leave it blank and finish OAuth in the browser later.
   - Keep adding accounts until you are done.

4. Run the backend:
   ```bash
   uv run mastodon_is_my_blog start --reload --port 8000
   ```

## Step 3: Run Frontend

1. Navigate to the web directory:
   ```bash
   cd web
   ```

2. Install dependencies (if not already done):
   ```bash
   npm install
   ```

3. Run the Angular dev server:
   ```bash
   ng serve --port 4200
   ```

## Step 4: Connect and Use

1. Open http://localhost:4200 in your browser
2. If you did not enter an access token during `init`, click "Connect Mastodon"
3. Authorize the application on Mastodon
4. You'll be redirected back to your blog console
5. Start writing and publishing posts!

## Features

- 📝 View your posts in a clean blog format
- 💬 View comments/replies on your posts
- ✏️ Edit posts (creates new post with updated content)
- 🎨 Blog-style UI with clean typography
- 📦 Static site generator for public viewing
- ✍️ Write and publish posts to Mastodon

## Future Features

- 🏷️ Tag filtering and organization
- 🔍 Search functionality

## Troubleshooting

### CORS Errors
Make sure both frontend and backend URLs match where you're actually running the servers.

### Authentication Not Working
1. Re-run `uv run mastodon_is_my_blog init` and double-check your client ID and secret
2. Verify the redirect URI in Mastodon matches exactly: `http://localhost:8000/auth/callback`
3. Check that you selected `read` and `write` scopes

### Posts Not Loading
1. Ensure you're authenticated (click Connect Mastodon if you skipped the token during setup)
2. Check the browser console for errors
3. Verify your backend is running on port 8000
