# Core concepts

Before Mastodon is My Blog (MIMB) feels intuitive, three ideas matter more than anything else.

## 1. Identity

An **identity** is one real Mastodon account.

MIMB is built for a single human with several Mastodon accounts, for example:

- a main account
- an art account
- a work account

You can connect as many identities as you like, mixing OAuth-connected and
manually-keyed accounts freely. The selected identity changes what you see
because each one has different follows, activity, and topic bundles.

## 2. Cache

MIMB keeps a **local cache** so it can organize Mastodon in ways the standard interface does not.

That cache powers:

- People views
- blog roll filters
- content buckets like software, links, and news
- unread counts
- bundle matching

## 3. Intentional sync

MIMB does not try to feel like a nonstop live stream. You refresh on purpose.

That is why the Admin page is important. It gives you clear moments to:

- refresh the cache
- backfill your history
- sync followed hashtags
- manage topic bundles

## Helpful language in the app

### Blog roll

Your **blog roll** is the set of people MIMB thinks are relevant for person-by-person reading.

### Storms

A **storm** is a long post or a self-thread that reads more like an essay than a quick update.

### Bundle

A **bundle** is a named topic collection in the Content area. It can combine several hashtags and search terms.

### Server follow

A **server follow** is a hashtag you already follow on Mastodon. MIMB can import those into Content as read-only groups.

### Catch-up

A **catch-up** job is a larger backfill process that goes deeper into cached history than a normal refresh.

## Why some things feel different from Mastodon

MIMB is trying to answer a different question.

The default Mastodon interface asks:

> "What is happening right now?"

MIMB asks:

> "What do I want to read, from whom, and in what shape?"
