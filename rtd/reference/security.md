# Security

Mastodon is My Blog (MIMB) is a local app that connects to your Mastodon account. That makes security less about "what data does a cloud vendor hold?" and more about "what does this app store on my machine, and how do I operate it safely?"

## What MIMB stores locally

| Item | Where it lives | Why it matters |
| --- | --- | --- |
| Account list and instance URLs | Local config on your machine | Tells MIMB which Mastodon identities exist. |
| Client ID, client secret, and access token | Your system keyring when available | These are sensitive credentials. |
| Cached posts, account data, notifications, and read state | Local SQLite database | Powers People, Content, filters, and archive-style browsing. |
| Chosen meta account and identity in the browser | Browser local storage | Remembers your local session context in the web UI. |

## What stays on Mastodon

Your real account still lives on your Mastodon server.

MIMB is not your social server. It is a local client that reads from and writes to the server you already use.

## Good security habits

### Keep it local

Run MIMB on your own machine unless you deliberately want to self-host it somewhere else.

### Protect your machine

If someone has access to your unlocked machine, they may also have access to your local cache and browser session.

### Treat access tokens seriously

If you think a token has leaked:

1. revoke the Mastodon app or token on your server
2. create a new one
3. reconnect MIMB

### Be careful with published output

If you use the static blog export, remember that anything you publish publicly is no longer only local.

## Practical expectations

MIMB does **not** depend on a vendor-run central cloud service for its normal local workflow.

That is good for privacy and control, but it also means you are responsible for:

- your backups
- your machine security
- deciding what you publish

## If keyring is unavailable

MIMB prefers to use your system keyring for secrets. If that is unavailable in your environment, setup becomes less ideal and deserves extra care.

For public-facing or long-term use, a working system keyring is the safer path.
