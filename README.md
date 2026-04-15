# 🐘 Mastodon is My Blog

My attempt to create an alternative Mastodon client based on a blogging interface instead of the infinite feed.

- Transform your tweet storms into a static eleventy blog.
- View your friends content in person centric way
- View your special interests in a focused way
- Write, edit, and manage your Mastodon posts in a clean, blog-style interface. (Kind of still in progress)

## Why?

Because I want to re-orient my mastodon usage from low value infinite doom scrolling to high value finite activities.

I want the UI to be human centric and encourage seeing people first.

I want the UI to encourage medium length writing as much as reading, including thought out drafts, as well as short
content and replies.

## Implemented Features

- Eleventy blog, published via GH Actions
- Local Client, which is a Python FastAPI+Sqlite data source and an Angular Website.
    - Downloads all my data to sqlite, used by blog engine
    - Downloads data of people I follow, hashtags I follow
        - Blog-reader like interface for people
        - Content hub for special interests (pictures, videos, software links, etc)
        - Discussion page (primitive, not done, shows threads my friends participated in)
        - Writing Page (primitive, not done)
        - Admin Page

Some design decisions

- Refresh is done by clicking a button. Content doesn't arrive in a stream.
- Doesn't feel like a mixed feed. All feeds are filtered, either by person or topic.
- The reader doesn't have any actions. Actions are done via link back to home instance.
- Client side hashtag bundles because viewing a hashtag on Mastodon is broken.
    - Why? Because `#python` and `#python314` and so on really should show in the same feed. This can only be achieved
      on vanilla Mastodon via the main feed, which is mixed with 99% unrelated content. Also, most hashtags have not
      much going on.
- I call the friends a blogroll and group them by
    - Top Friends (people who are mutuals and have ever commented on my content)
    - Mutuals (they at least read my content)
    - Bots (No one is there, this is just content)
    - Broadcasters (Like bots, they write but never interact, at least not with me)
- Retweets are suppressed everywhere. But not quote tweets.

## Roadmap

- Analytics page - show performance in one place, not on every post

## Other good features

- Treat Mastodon as your personal blog engine. Done! Finally.
- Keep full control with local hosting. This would be ruinously expensive for me to host this for others.
- Beautiful, distraction-free writing interface. Partial!
- Engage with comments/replies easily. Not really!
- Your data stays on your Mastodon instance. Sort of! If you use Github pages, you got a copy of your posts in two
  places now. The rest of your data is local to your machine.

## Quick Start

See [SETUP.md](SETUP.md) for detailed setup instructions.

```bash
# 1. Install the package
uv sync

# 2. Run interactive account setup
uv run mastodon_is_my_blog init

# 3. Start the backend
uv run mastodon_is_my_blog start --reload

# 4. Start the frontend (in another terminal)
cd web && ng serve
```

Open http://localhost:4200. If you skipped the access token during `init`, use the web login flow to finish connecting that account.

## Static Storm Export

Build the Eleventy blog export for your own long posts and self-reply threads into `docs\`:

```bash
npm --prefix docs-src install
npm --prefix docs-src run build
```

## Architecture

- **Backend**: FastAPI + mastodon.py + SQLAlchemy
- **Frontend**: Angular (standalone components)
- **Storage**: SQLite for tokens and caching, Mastodon for content

## More Roadmap

- [ ] Draft saving
- [ ] Analytics dashboard
- [ ] RSS feed links. Maybe already done? Check eleventy.

## Why not a single user instance?

First off, that is really a different concept. A single user instance without massive customization is still going to be
same experience as mastodon.social, both for people reading your content and for you reading other people's content. 

It costs a minimum of $10 a month and requires a server to be running all the time. Administering a server is a burden.

I want this to be as burdensome as using a mastodon client and have a way to use it for free.

## License

MIT
