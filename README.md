# 🐘 Mastodon is My Blog

An alternative Mastodon client based on a blogging interface instead of the infinite feed.

- View your friends content in person centric way
- Publish your tweet storms into a static blog.
- View your special interests in a focused way
- Write, edit, and manage your Mastodon posts in a clean, blog-style interface.

## Installation

```bash
pipx install mastodon-is-my-blog
# initialize your accounts and API keys
mimb init
# launch webserver and website
mimb start
```

Documentation found [here](https://mastodon-is-my-blog.readthedocs.io/en/latest/)

Lite Client found [here](https://matthewdeanmartin.github.io/mastodon_is_my_blog/mimb_lite/)

Example published blog [here](https://matthewdeanmartin.github.io/mastodon_is_my_blog/)

## Why?

Because I want to re-orient my mastodon usage from low value infinite doom-scrolling to high value finite activities.

I want the UI to be human centric and encourage seeing people first.

I want the UI to encourage medium length writing as much as reading, including thought out drafts, as well as short
content and replies.

## Implemented Features

- Publishes static blog from your long content.
- Local Client
  - Blog-reader like interface for people.
  - Content hub for special interests (pictures, videos, software links, etc)
  - Discussion page
  - Writing Page
  - Admin Page

### Some design decisions

- I call the friends a blogroll and group them by
    - Top Friends (people who are mutuals and have ever commented on my content)
    - Mutuals (they at least read my content)
    - Bots (No one is there, this is just content)
    - Broadcasters (Like bots, they write but never interact, at least not with me)
- Removed dark patterns
  - Refresh is done by clicking a button. Content doesn't arrive in a stream.
- Less noisy. 
  - All feeds are filtered, either by person or topic.
  - Retweets are corralled into one place, they don't flood your feed.
- Client side hashtag bundles because viewing a hashtag on Mastodon is broken.
    - Why? Because `#python` and `#python314` and so on really should show in the same feed. This can only be achieved
      on vanilla Mastodon via the main feed, which is mixed with 99% unrelated content. Also, most hashtags have not
      much going on.

## Roadmap

- Paid hosted option.

## Other good features

- Treat Mastodon as your personal blog engine. Done! Finally.
- Keep full control with local hosting. This would be ruinously expensive for me to host this for others.
- Beautiful, distraction-free writing interface. Partial!
- Engage with comments/replies easily. Not really!
- Your data stays on your Mastodon instance. Sort of! If you use Github pages, you got a copy of your posts in two
  places now. The rest of your data is local to your machine.

## Static Storm Export

Build the Eleventy blog export for your own long posts and self-reply threads into `docs\`:

```bash
npm --prefix docs-src install
npm --prefix docs-src run build
```


## Why not a single user instance?

First off, that is really a different concept. A single user instance without massive customization is still going to be
same experience as mastodon.social, both for people reading your content and for you reading other people's content. 

It costs a minimum of $10 a month and requires a server to be running all the time. Administering a server is a burden.

I want this to be as burdensome as using a mastodon client and have a way to use it for free.

## License

MIT

## Project Links

- [GitHub](https://github.com/matthewdeanmartin/mastodon_is_my_blog)
- [PyPI](https://pypi.org/project/mastodon-is-my-blog/)
- [Documentation](https://mastodon-is-my-blog.readthedocs.io/en/latest/)
- [Bug Tracker](https://github.com/matthewdeanmartin/mastodon_is_my_blog/issues)
- [Change Log](https://github.com/matthewdeanmartin/mastodon_is_my_blog/blob/main/CHANGELOG.md)
