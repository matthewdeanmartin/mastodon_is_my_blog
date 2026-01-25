# Coding guidelines

- Always type annotate
- Always get as much data from mastodon's APIs to cache locally as possible
- Don't hide exceptions with excessive error handling, let them raise.
- If you are catching Exception, you don't have enough info to know if you are catching a known event or hiding a bug.
- Never number your comments. It creates nasty diffs for future changes.

## Architecture

- This is a FastAPI app with sqlalchemy as the ORM. You must not change that.

## Changes

- The app is in development and not in production. There are no legacy clients.
- It is more important to have clean data models than to preserve backwards compatibility. If a field becomes required we can't be doing weird ass assumptions to fill in the blanks to preserve backwards compat with clients that don't exist