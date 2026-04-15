# Queries and filters

Mastodon is My Blog (MIMB) depends on filters more than most Mastodon clients do. This page explains them in plain English.

## The big idea

MIMB uses the word **filter** for several different jobs:

- narrowing the people you browse
- narrowing the kinds of posts you read
- defining topic bundles
- choosing how a topic view is ordered

## People: blog roll filters

These control **which accounts** appear in the left sidebar.

| Filter | What it means in practice |
| --- | --- |
| All | Everyone the current identity follows in MIMB's local reading set. |
| Top Friends | Mutuals who have actually interacted with you, not just silent follows. |
| Mutuals | People you follow who also follow you back. |
| Chatty | Accounts whose posts lean heavily toward replies and conversation. |
| Broadcasters | Accounts that mostly post outward and reply less. |
| Bots | Accounts marked as bots. |

## People: post filters

These control **what kind of posts** you see in the reading area.

| Filter | Plain-English meaning |
| --- | --- |
| Storms | Long posts or self-threaded writing that reads like a mini-essay. |
| Shorts | Short standalone posts without much extra structure. |
| Questions | Posts that look like they are asking something. |
| News | Posts MIMB classifies as news-like sharing. |
| Cool Software | Posts MIMB classifies as software-related finds. |
| Pictures | Posts with images or other media. |
| Videos | Posts with video. |
| Discussions | Replies to other people, useful when you want conversation rather than monologues. |
| Links | Posts containing external links. |
| Reposts | Present in the interface, but this area is still evolving. Treat it as work in progress for now. |

## Special People views

### My Blog

Shows your own account in the current identity context.

### Everyone's Blog

Shows a wider combined reading view instead of one person at a time.

### Next Blog

Moves you to the next account in the current filtered blog roll.

## Content: bundle terms

Bundles in Content can use two kinds of query terms.

### Hashtag

Use a hashtag term when you want:

- exact tag-based discovery
- predictable grouping
- a clearer topic boundary

Example:

```text
python
```

That behaves like a `#python` topic.

### Search

Use a search term when you want:

- broader discovery
- posts that may not share one exact hashtag
- your server's own search behavior

Example:

```text
python jobs
```

Important: search results depend on what your Mastodon server can find and return, so they may feel less exact than hashtag bundles.

## Content: sort and scope modes

These are the common meanings:

| Mode | Meaning |
| --- | --- |
| Recent | Newest first. |
| Popular | More engagement rises upward. |
| Following | Stay centered on your current network context. |
| Everyone | Broaden the view where that tab supports it. |

## Link grouping

In the Links tab, MIMB groups posts by the linked domain.

That lets you answer questions like:

- Which sites does my network keep recommending?
- Which domain is getting the most attention today?

## Pagination

MIMB loads more items as you keep scrolling. You do not have to manage page numbers manually.

## Why filters may feel opinionated

They are. MIMB is built around the idea that **shape matters**:

- long writing is different from quick notes
- reply-heavy accounts feel different from broadcasters
- topic reading is different from person reading

That is the whole point of the app.
