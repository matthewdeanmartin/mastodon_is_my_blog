# Lite Epic — Sprint 01: Blog Roll Filters

Goal of the epic: bring the Lite client (`web/src/lite/`, pure-browser, no mimb
server) to near parity with the server-backed UI. This sprint delivered the
"Blog Roll Filters" people classification from `app.component.html` /
`routes/accounts.py`, rebuilt on a small API budget plus a persistent
localStorage evidence ledger.

## What shipped

### Evidence ledger (`lite-people.ts`, new)
- `PersonEvidence` per account, stored as a `PeopleLedger` map in localStorage
  under cache key `people-ledger` (via `LiteStorageService.writeCache`).
- **Now-and-forever facts** — once observed, never unset, so classifications
  survive sessions where we only load a few pages:
  `everMutual`, `everMentionedMe`, `everFavouritedMe`, `everBoostedMe`,
  `everStatusNotified`, `iRepliedToThem`.
- **Latest observations** (overwritten when fresher): `followsMe`,
  `followersCount`, `bot`, `lastStatusAt`.
- **Reply-ratio sample** for chatty/broadcasters: `sampledPosts`,
  `sampledReplies`, deduped by `sampledStatusIds` (capped at 100 ids) so a
  re-fetched page doesn't double count.
- `snapshot`: thin `LiteAccount` kept for people we *don't* follow (needed so
  Readers can list strangers who boosted us).

### Classification (`matchesPeopleFilter`) — parity map vs `routes/accounts.py`
| Filter | Server rule | Lite rule | Divergence |
|---|---|---|---|
| all | everyone I follow | loaded following pages | only ~160 loaded |
| mutuals | is_followed_by | relationship.followed_by OR sticky everMutual | mutual is forever by design (user request) |
| top_friends | mutual + any notification | same, from ~2 notification pages + sticky flags | — |
| readers | anyone who reblogged me | everBoostedMe, includes non-follows via snapshot | — |
| chatty | reply ratio > 50% of cached posts | sampled ratio > 50% (min 5 sampled) OR everMentionedMe | mentions count as chat evidence |
| broadcasters | ratio < 20%, statuses > 100 | sampled ratio < 20% (min 5), statuses_count > 100 | — |
| idols | I replied, no inbound, not follower | same via own-status `in_reply_to_account_id` | — |
| bots | bot flag | bot flag | — |
| lively | last_status_at ≤ 30d | same (following API returns last_status_at) | — |
| graveyard | null or > 90d | same | works, despite earlier assumption it wouldn't |
| parasocials | >10k followers, no follow-back | same threshold (10k, `PEOPLE_THRESHOLDS.parasocialFollowersMin`) | user mentioned 20k in passing; kept 10k for server parity — one constant to change |
| other | none of the above | none of the above | — |

### API calls & budget (`lite-mastodon.service.ts`, `lite.limits.ts`)
- `following()` now paginates via the **Link header** (`parseNextLink`),
  2 pages × 80 = up to 160 friends. (Note: `max_id` on following is an
  internal cursor, NOT an account id — Link header is the only correct way.)
- New `notifications()` — 2 pages, `types[]=mention,favourite,reblog,status,follow`.
- New `relationships(ids)` — chunked at 80 ids/call.
- Budget for initial load: 1 (own statuses) + 2 (following) + 2 (notifications)
  + 2 (relationships) = 7 of `maxCallsPerOperation: 10`. Evidence gathering is
  best-effort: it checks `budget.remaining` before each phase and swallows
  failures, keeping partial evidence.
- Every status window loaded afterwards (home feed on Content/Forums, clicking
  a person) is absorbed into the ledger (`absorbObservedStatuses`), so chatty /
  broadcaster / lively evidence accretes as the user browses. Free calls.

### UI (`lite-app.component.*`)
- People panel renamed "Blog roll", chip row with the 12 filters, count shows
  "N of M loaded", empty state message.
- Sample mode gets a fixture ledger (`sampleLedger()` in `lite-fixtures.ts`)
  so chips demo something.

### Models
- `LiteAccount` gained optional `bot`, `locked`, `last_status_at`;
  `LiteStatus` gained optional `in_reply_to_account_id`. Optional to avoid
  breaking existing fixtures/specs.

## Verification
- `npx ng test lite --no-watch` — 43/43 pass (10 new ledger tests in
  `lite-people.spec.ts`, 3 new service tests).
- `npx ng test web --no-watch` — 165/165 pass.
- `npx ng lint lite --max-warnings 0` — clean.
- `npx ng build lite` — clean (note: `lite-app.component.scss` is within 16
  bytes of its 8 kB budget; next styling addition must trim something).
- NOT yet verified against a live instance. That is the first task next sprint.

## Handoff — Sprint 02 candidates
1. **Live-instance smoke test.** Connect to a real Mastodon account and confirm:
   notifications `types[]` params accepted everywhere (some forks differ),
   relationships chunk size 80 accepted, Link pagination on following works.
2. **Evidence refresh staleness.** `gatherPeopleEvidence` runs only on initial
   load. Add a "reclassify" affordance or refresh evidence when
   `people-ledger` is older than `cacheTtlMs`.
3. **Badges on people rows** — show top category per person (server UI shows
   filter lists; a small chip per row would help discovery).
4. **More friends over time.** With Link-header cursors persisted in the
   ledger, later sessions could fetch *different* following pages (pages 3-4)
   and grow coverage past 160 without ever loading all 1000 at once.
5. **Ledger hygiene**: entries for people you unfollowed are never pruned;
   consider a cap or last-touched eviction (localStorage is ~5 MB; each entry
   is small but sampledStatusIds ×1000 people adds up).
6. **Sort parity**: server sorts most filters by `last_status_at` desc,
   parasocials by follower count desc. Lite keeps following-order; trivial to
   add in `visiblePeople`.
7. **`status` notifications** currently only set a sticky flag; they could
   also update `lastStatusAt`.

## Gotchas for the next bot
- Lite lives in `web/src/lite/` (NOT `web/app/lite`). Angular projects: `web`
  and `lite` in `web/angular.json`.
- Run tests with `npx ng test lite --no-watch` from `web/`. Raw `npx vitest`
  fails on Angular TestBed specs (missing JIT setup) — don't chase those
  failures.
- HttpTestingController + sequential paginated requests: you must `await` a
  macrotask (`setTimeout 0`) after `flush()` before `expectOne` finds the next
  request (see `settle()` in `lite-mastodon.service.spec.ts`).
- OAuth scope is `read write:statuses` — `read` already covers notifications
  and relationships, no scope change was needed.
- No `_`-prefixed private names (project rule, see CLAUDE.md).
