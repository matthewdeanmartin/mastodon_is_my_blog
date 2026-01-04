# 🐘 Mastodon is My Blog

A local-first blogging interface for Mastodon. Write, edit, and manage your Mastodon posts in a clean, blog-style interface.

## Why?

- 📝 Treat Mastodon as your personal blog engine
- 🏠 Keep full control with local hosting
- 🎨 Beautiful, distraction-free writing interface
- 💬 Engage with comments/replies easily
- 🔒 Your data stays on your Mastodon instance

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
- **Storage**: SQLite for tokens, Mastodon for content

## Roadmap

- [ ] Static site generation for public viewing
- [ ] Markdown support
- [ ] Draft saving
- [ ] Tag/category organization
- [ ] Analytics dashboard
- [ ] RSS feed generation

## License

MIT