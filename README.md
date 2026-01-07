# 🐘 Mastodon is My Blog

My attempt to create an alternative Mastodon client based on a blogging interface instead of the infinite feed.

Write, edit, and manage your Mastodon posts in a clean, blog-style interface.

## Why?

Because I want to re-orient my mastodon usage from low value infinite doom scrolling to high value finite activities.

I want the UI to be human centric and encourage seeing people first.

I want the UI to encourage medium length writing as much as reading, including thought out drafts, as well as short
content and replies.

## Roadmap

- Writing blog posts
- Discussion - shows all posts with past replies
- Looking at pretty pictures
- Finding Youtube suggestions - filters to all posts
- Find cool software - filters to all posts mentioning github
- Analytics page - show performance in one place, not on every post

## Other good features

- Treat Mastodon as your personal blog engine
- Keep full control with local hosting
- Beautiful, distraction-free writing interface
- Engage with comments/replies easily
- Your data stays on your Mastodon instance

## Quick Start

See [SETUP.md](SETUP.md) for detailed setup instructions.

```bash
# 1. Configure your .env file with Mastodon credentials
cp .env.example .env

# 2. Start the backend
uvicorn mastodon_is_my_blog.main:app --reload

# 3. Start the frontend (in another terminal)
cd web && ng serve
```

Open http://localhost:4200 and click "Connect Mastodon"!

## Architecture

- **Backend**: FastAPI + mastodon.py + SQLAlchemy
- **Frontend**: Angular (standalone components)
- **Storage**: SQLite for tokens and caching, Mastodon for content

## More Roadmap

- [ ] Static site generation for public viewing
- [ ] Draft saving
- [ ] Tags filtering, tags view using hashtags
- [ ] Analytics dashboard
- [ ] RSS feed links
- [ ] Support multiple accounts

## Why not a single user instance?

It costs a minimum of $10 a month and requires a server to be running all the time. Administering a server is a burden.

I want this to be as burdensome as using a mastodon client and have a way to use it for free.

## License

MIT