# DB-Backed PR List with Background Sync — Design Spec

**Date:** 2026-08-28
**Branch:** `worktree-pr-sync-db`
**Status:** Approved design

## Problem

The PR list tab fetches live from GitHub on every load and every filter change: one
`gh pr list --limit 100` requesting ~25 JSON fields per PR, including `reviews` (full review
history) and `statusCheckRollup` (every CI check). On busy repos GitHub's backend times out on
that query and returns 504. The existing retry-with-backoff in `run_gh_command` doesn't help
because the query is deterministically too heavy — every retry fails the same way. Navigation
and filtering are also slow even when the query succeeds, since every interaction is a full
GitHub round-trip.

## Goals

1. The PR list is served from a local SQLite table — instant navigation and filtering, and
   GitHub 5xx flakiness never reaches the UI.
2. **No PR data is dropped** — the full field set fetched today is stored per PR.
3. A background sync worker keeps the table fresh using only small, 504-resistant queries.
4. Each PR card shows how fresh its data is (`fetched_at`) and has a per-card refresh button
   that live-fetches just that PR.
5. Data is segregated per repo/account: every row and query is keyed by `owner/repo`
   (matching the existing `repo TEXT` convention in the DB module).
6. Sync behavior is tunable via an internal `pr_sync` config block with sensible defaults.

## Non-goals

- Divergence (ahead/behind) stays a separate on-demand batch endpoint, unchanged.
- Analytics, CI tab, merge queue, reviews — unchanged (they have their own caches).
- No websocket/live-push; freshness comes from polling + visible timestamps.
- No sync of PRs closed/merged more than `history_days` ago (they fall out of the window
  and are pruned).

## Scope decisions (from design discussion)

| Decision | Choice |
|----------|--------|
| Which PRs synced | Open PRs + closed/merged updated within last **180 days** |
| Which repos synced | Every repo opened in the UI, auto-registered on first visit, capped by `max_synced_repos` (LRU by last visit; over-cap repos use the live path) |
| GitHub-only filters | **Hybrid**: numbers-only live search joined against DB rows |
| Initial backfill | Acceptable to be slow; runs in background; open PRs hydrate first |

---

## Architecture

### 1. Storage (`backend/database/synced_prs.py`)

Two tables, created in `Database._init_db` following existing patterns:

```sql
CREATE TABLE IF NOT EXISTS synced_repos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL UNIQUE,              -- "owner/name"
    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_visited_at DATETIME,
    last_synced_at DATETIME,                -- last successful incremental sync
    backfill_done INTEGER NOT NULL DEFAULT 0,
    backfill_error TEXT                     -- last backfill failure, for observability
);

CREATE TABLE IF NOT EXISTS synced_prs (
    repo TEXT NOT NULL,                     -- "owner/name"
    pr_number INTEGER NOT NULL,
    state TEXT NOT NULL,                    -- OPEN | CLOSED | MERGED
    is_draft INTEGER NOT NULL DEFAULT 0,
    author TEXT,
    created_at TEXT,
    updated_at TEXT,
    closed_at TEXT,
    merged_at TEXT,
    data TEXT NOT NULL,                     -- full PR JSON (every field fetched today)
    fetched_at DATETIME NOT NULL,
    PRIMARY KEY (repo, pr_number)
);
CREATE INDEX IF NOT EXISTS idx_synced_prs_repo_state ON synced_prs(repo, state);
CREATE INDEX IF NOT EXISTS idx_synced_prs_repo_updated ON synced_prs(repo, updated_at DESC);
```

The scalar columns exist only for cheap SQL narrowing (state, author, draft, date ranges).
Everything else filters in Python against the parsed `data` JSON — at the few thousand rows a
180-day window holds, this is milliseconds. `reviewStatus` / `ciStatus` / `currentReviewers`
are **not** stored; they are computed at serve time by the same `pr_service` helpers used
today, so there is exactly one source of truth and no recompute-on-schema-change migrations.

New store class `SyncedPRDB` with methods: `register_repo`, `touch_repo_visit`,
`get_synced_repos`, `mark_backfill_done`, `set_backfill_error`, `update_last_synced`,
`upsert_pr` / `upsert_prs`, `get_prs(repo, state, ...)` (SQL narrowing), `delete_pr`,
`prune_old_prs(repo, cutoff)`, `get_repo_status(repo)`.

### 2. Sync worker (`backend/services/pr_sync_worker.py`)

A daemon thread started from `app.py` alongside the existing watchers
(`auto_review_watcher_loop` pattern). Loop:

```
every poll_interval_seconds:
    repos = registered repos, minus exclude_repos,
            ordered by last_visited_at DESC, capped at max_synced_repos
    for repo in repos:
        if not backfill_done: backfill(repo)
        else: incremental_sync(repo)
```

**Backfill** (first visit):
1. Fetch PR numbers only — two light queries (each `--json number`, so tiny and
   504-resistant): open PRs, then closed/merged with `updated:>=<today - history_days>`.
2. Hydrate each number via `gh pr view <n> --json <full field set>` in a small
   `ThreadPoolExecutor` (4 workers), upserting rows as they land — **open PRs first**, so the
   main view fills within seconds while history backfills behind it.
3. On completion set `backfill_done = 1`; on failure record `backfill_error` and retry next
   cycle (already-hydrated rows are kept; hydration is idempotent upserts).

**Incremental sync** (each cycle):
1. Numbers-only query: `--state all --search "updated:>=<last_synced - 10 min slack>"`.
2. Re-hydrate just those PRs (state transitions — closed, merged, reopened — are picked up
   naturally because the row's `state` comes from the fresh fetch).
3. Prune closed/merged rows with `updated_at` older than `history_days`.
4. Update `last_synced_at`.

Every gh call goes through the existing `run_gh_command` retry logic. A failed cycle is
logged and simply retried next cycle — the UI keeps serving the last good data, and the
staleness is visible via timestamps.

Single-PR hydration reuses one shared field-set constant with `pr_routes.PR_JSON_FIELDS`
(moved to a shared module to avoid divergence).

### 3. API changes (`backend/routes/pr_routes.py`)

`GET /api/repos/<owner>/<repo>/prs` becomes a three-way dispatch:

1. **DB path** (repo registered + backfill done + no GitHub-only filter active):
   `touch_repo_visit`, SQL-narrow by state/author/draft/dates, apply the remaining filters in
   Python against stored JSON (label/assignee/milestone/branch/exclusion/title-body-text
   logic ported from the gh-qualifier semantics; review/CI post-filters reuse today's code
   verbatim), sort (created/updated locally), apply `limit`, respond.
2. **Hybrid path** (DB-ready but a GitHub-only filter is active — `mentions`, `commenter`,
   `involves`, `reactions`, `interactions`, `comments`, `linked`, search-in-comments, or a
   comments/reactions/interactions sort): run the existing `PRFilterBuilder` query but with
   `--json number` only (tiny, reliable), then serve the matching rows from the DB
   **preserving GitHub's returned order**. Numbers not in the DB (edge: outside the 180-day
   window) are hydrated on the spot.
3. **Live path** (repo unregistered / over cap / excluded / backfill not done): today's
   behavior, unchanged. First-visit UX therefore equals the status quo while backfill runs.
   Graceful degradation: if the live fetch raises `TransientGitHubError` and partial DB rows
   exist (mid-backfill), serve the partial rows with `syncStatus: "backfilling"` instead of
   returning 503.

Response gains metadata (per-PR `fetchedAt` injected into each PR dict; top level):

```json
{ "prs": [...], "sync": { "status": "ready|backfilling|live", "lastSyncedAt": "..." } }
```

Visiting the endpoint also registers the repo (`register_repo` upsert), which is what makes
first visits kick off backfill.

New endpoint — per-card refresh:

```
POST /api/repos/<owner>/<repo>/prs/<int:pr_number>/refresh
```

Live `gh pr view` with the full field set, upsert into `synced_prs`, return the processed PR
dict (same shape as list items, incl. fresh `fetchedAt`). On a 404 (PR deleted), delete the
row and return 404.

### 4. Frontend

- `api/types.ts`: `PR` gains `fetchedAt?: string`; `PRsResponse` gains
  `sync?: { status: 'ready' | 'backfilling' | 'live'; lastSyncedAt: string | null }`.
- `api/prs.ts`: new `refreshPR(owner, repo, prNumber)`.
- **PR card**: relative "data from Xm ago" timestamp + refresh icon button with spinner;
  the response row replaces the card's PR in place.
- **List header**: repo-level "synced Xs ago" indicator when `sync.status === 'ready'`; a
  "backfilling PR history…" notice when `backfilling`, during which the list re-polls every
  few seconds to pick up newly hydrated rows; nothing shown on `live` (status quo).
- Pagination, filter tabs, and all existing UI behavior unchanged.

### 5. Configuration (`config.json` → `pr_sync` block)

All defaults internal (in `backend/config.py`); the block is optional in `config.json`:

```json
"pr_sync": {
  "enabled": true,
  "poll_interval_seconds": 120,
  "history_days": 180,
  "max_synced_repos": 10,
  "exclude_repos": []
}
```

`enabled: false` disables the worker and makes `/prs` use the live path everywhere —
a clean kill switch back to today's behavior.

## Error handling

- Worker: every repo cycle is wrapped; a repo's failure never blocks other repos. Transient
  gh errors ride the existing retry/backoff; exhausted retries log a warning and defer to
  the next cycle.
- Per-card refresh failures return the gh error to the UI (toast/inline), leaving the stale
  row and its timestamp visible.
- SQLite: per-call connections (existing `Database.connection()` pattern) keep the worker
  thread and Flask request threads safe without shared state.

## Testing

- **Store**: CRUD, upsert idempotence, prune window, LRU cap ordering, repo segregation
  (two repos' rows never bleed into each other's queries).
- **Filter parity**: table-driven tests asserting the DB path's Python filters match the
  documented gh-qualifier semantics for every Basic/Review/People/Dates filter, plus
  review/CI post-filter reuse.
- **Worker**: backfill (open-first ordering, resumability after failure), incremental sync
  (updated-since query, state transitions, prune), all with `run_gh_command` mocked.
- **Routes**: three-way dispatch selection, hybrid order preservation, refresh endpoint
  upsert + 404 delete, transient-error partial-serve fallback.
- **Frontend**: helper logic (relative-time formatting, sync-status display rules) verified
  via the esbuild bundle-and-run approach.

## DESIGN.md

Implementation updates `docs/DESIGN.md` with a new "PR List Sync" feature section, updates
the PR Filtering + API Endpoints + Configuration sections, and refreshes the CLAUDE.md index
line numbers.
