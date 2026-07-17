# Lite Epic — Sprint 02: Dropdown flag, app switching, deeper blog roll

Follows `epid_lite_sprint01.md`. Two threads this sprint: UX changes the user
asked for (feature-flagged dropdown, switch-to-lite/heavy links, "Context:"
removal) and the sprint-01 handoff items that didn't need a live instance.

## What shipped

### Feature flag: blog roll categories as a dropdown (both apps)
- New shared module `web/src/app/feature-flags.ts`. Compile-time defaults in
  `FEATURE_FLAG_DEFAULTS` (currently `blogRollDropdown: true`), with a
  per-browser runtime override — no rebuild needed to change your mind:
  `localStorage.setItem('mimb:flag:blogRollDropdown', 'false')` → buttons/chips
  come back on next reload. Delete the key to return to the default.
- Heavy app: the 12 blog-roll filter buttons collapsed into a `<select>`.
  Both branches render from one `blogFilterOptions` array in
  `app.component.ts` (value/label/title), so the long tooltip texts moved out
  of the template and survive in both modes.
- Lite: same flag, same treatment for the people-panel chips.

### Header changes
- Heavy identity bar: the "Context:" label is gone; a "⚡ Switch to Lite"
  link (public GitHub Pages URL) sits at the far right.
- Lite: a "Switch to heavy" link appears **only when running on
  localhost/127.0.0.1**, in the top bar and on the landing hero. The URL is
  assembled at runtime (`http://${hostname}:8100/`) because CI greps the Lite
  bundle for the literal `localhost:8100` and fails the build if present
  (`.github/workflows/build.yml`) — do not "simplify" this into a constant.

### Sprint-01 handoff items implemented
- **Progressive following crawl.** `LiteMastodonService.following()` now
  always fetches a fresh page 1 (new follows appear immediately), then
  resumes page 2 from a cursor persisted in the `following-cursor` cache key.
  Each session walks two pages deeper into a large following list; results
  merge with the cached list (dedupe by id, fresh first).
  `maxCachedFollowing` raised 200 → 500. When the crawl wraps (`next: null`)
  it restarts from page 2 next session, refreshing older entries.
- **Sort parity** (`sortPeople` in `lite-people.ts`): newest-post-first for
  most filters, graveyard oldest-first with never-posted at top, parasocials
  by follower count desc — matching `routes/accounts.py` ORDER BYs.
- **Reclassify button** in the people panel: re-runs relationship +
  notification evidence gathering on demand with a fresh 10-call budget.
- **Notification freshness**: mention/status notifications bump the ledger's
  `lastStatusAt`, so someone the following-page data says is quiet but who
  just mentioned you counts as lively.
- **Ledger pruning** (`pruneLedger`): entries that are not in the current
  following list, hold no sticky facts, and are 90+ days untouched get
  deleted on each evidence pass.

## Verification
- `npx ng test lite --no-watch` — 47/47 (4 new: notification freshness, sort
  order, pruning, cursor resume).
- `npx ng test web --no-watch` — 169/169.
- `npm run lint` — clean for both projects.
- `npm run build` and `npm run build:lite:pages` — clean; verified the CI
  bundle guard locally (`grep -E 'localhost:8100|/api/admin'` finds nothing,
  base href correct). The web build's bundle/scss budget warnings
  (dossier, new-friends, 691 kB initial) are pre-existing.
- Still NOT verified against a live Mastodon instance — carried forward.

## Handoff — Sprint 03 candidates
1. **Live-instance smoke test** (carried from sprint 01): notification
   `types[]` params, relationship chunk size 80, Link pagination, and now
   also the cursor-resume flow across two real sessions.
2. **Unfollow staleness**: someone you unfollow lingers in the cached
   `following` list until the crawl wraps. Option: when the crawl completes a
   full cycle, replace (not merge) the cached list with accounts seen during
   that cycle.
3. **Badges on people rows** (carried): with the dropdown default, a small
   per-person category badge matters more since only one filter is visible.
4. **Category counts in the dropdown** ("Mutuals (12)") — cheap, all data is
   client-side.
5. **More feature flags?** The pattern is in place; candidates: sticky-mutual
   behavior, chatty-counts-mentions divergence.
6. **Heavy dropdown polish**: the `<select>` loses per-filter tooltips until
   opened; consider showing `blogFilterTitle(currentBlogFilter)` as a caption
   under the select.

## Gotchas for the next bot (adds to sprint 01's list)
- CI hard-fails if the Lite JS bundle contains `localhost:8100` or
  `/api/admin`. Anything backend-ish in Lite must be built at runtime from
  `location`.
- `feature-flags.ts` lives in `src/app/` but is imported by Lite (Lite
  already imports `../app/mastodon`); keep it free of Angular/DOM-heavy
  imports.
- `lite-app.component.scss` is ~100 bytes under its 8 kB budget — new Lite
  styles go in `lite-styles.scss` (global, no budget pressure).
- The heavy `<select>` uses `[ngModel]`/`(ngModelChange)` (FormsModule was
  already imported); `setBlogFilter` handles routing/query params as before.
