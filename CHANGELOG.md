# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Publish buttons
- CLI surfaces more admin commands
- Postgres support

### Fixed
- Admin page now organized with left tab
- Performance problem with content hub/hashtags
- Find friends tab matches rest of theme
- Onboarding no longer so user hostile
- Error log and API observability page is back

## [0.4.1] - 2026-07-02
### Fixed
- Write tab no longer defaults the reply/post account to the first connected identity, ignoring the account active in the top bar — it now always posts as the active account, with no separate account picker.
- "My Blog" header and default home view no longer get stuck on whichever identity happened to load first — they now always track the account actually selected in the top bar.
- Drafts were leaking across every connected account (any account could see, open, edit, and delete any other account's drafts) — draft list/get/update/delete/publish now require and enforce a matching `identity_id`.

## [0.4.0] - 2026-05-03
### Added
- Observability for self-monitoring API usage
- More post and blog roll filters
- Discover new friends feature
- Error log tracking in website
- Content hashtag integration

### Changed
- Discussions now have reasonable groupings

### Fixed
- Timezone bug on certain pages

## [0.3.0] - 2026-04-20
### Added
- Writing and reply functionality
- Quality of life improvements

## [0.2.0] - 2026-04-19
### Added
- Analytics support
- Improved hashtag functionality
- Quality of life improvements

## [0.1.0] - 2026-04-17
### Added
- Blog-like "Storms" feed for reading
- Forum-like "Discussion" feed for single discussions
- Special links including My Blog, Everyone's Blog, and Next Blog
- Post-seen tracking to mark viewed content
- Filters for Storms, Shorts, Questions, News, Cool Software, Pictures, Discussions, and Links
- Prefetch caching of blog roll users
- Blog initialization with own posts
- Page to post single content

[0.4.0]: https://github.com/matthewdeanmartin/mastodon_is_my_blog/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/matthewdeanmartin/mastodon_is_my_blog/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/matthewdeanmartin/mastodon_is_my_blog/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/matthewdeanmartin/mastodon_is_my_blog/releases/tag/v0.1.0
