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

## Step 2: Configure Backend

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your Mastodon credentials:
   ```bash
   MASTODON_BASE_URL=https://mastodon.social  # or your instance
   MASTODON_CLIENT_ID=your_client_id_from_step_1
   MASTODON_CLIENT_SECRET=your_client_secret_from_step_1
   APP_BASE_URL=http://localhost:8000
   FRONTEND_URL=http://localhost:4200
   SESSION_SECRET=generate-random-string-here
   DB_URL=sqlite+aiosqlite:///./app.db
   ```

3. Install Python dependencies:
   ```bash
   pip install -e .
   ```

4. Run the backend:
   ```bash
   uvicorn mastodon_is_my_blog.main:app --reload --port 8000
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
2. Click "Connect Mastodon" button
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
Make sure both frontend and backend URLs in `.env` match where you're actually running the servers.

### Authentication Not Working
1. Double-check your client ID and secret in `.env`
2. Verify the redirect URI in Mastodon matches exactly: `http://localhost:8000/auth/callback`
3. Check that you selected `read` and `write` scopes

### Posts Not Loading
1. Ensure you're authenticated (click Connect Mastodon)
2. Check the browser console for errors
3. Verify your backend is running on port 8000