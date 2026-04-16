# PR Timelines — Design Spec

**Date:** 2026-04-16
**Branch:** `feature/pr-timeline`
**Status:** Approved, ready for implementation plan

## 1. Overview

PR Timelines is a new feature that surfaces every lifecycle event for a single pull request in a full-screen, interactive, visually polished vertical timeline. Users launch it from a **Timeline** button on any PR card (in the PR list) or merge queue card, see a color-coded, expandable event feed, filter by event type, and keep viewing while live updates stream in for open PRs.

### 1.1 Goals

- Provide a focused, single-PR deep-dive view for reviewing, debugging, and understanding PR history.
- Render all relevant GitHub PR events in one chronological stream: opened, commits, comments, reviews (approve / changes_requested / commented), review_requested, ready_for_review, convert_to_draft, closed, reopened, merged, head_ref_force_pushed.
- Feel modern and sleek — smooth animations, color-coded event types, markdown-rendered bodies.
- Stay performant — SQLite-backed caching, stale-while-revalidate, polling only while the modal is open.

### 1.2 Non-goals

- Editing/replying to comments from the timeline (read-only view).
- Timeline views for issues (this is PR-specific; issue timelines may reuse components later).
- Cross-PR aggregate views (that's Analytics' job).
- Webhook-based push updates — this is a local single-user tool; polling is sufficient.

## 2. Architecture

```
PRCard / QueueCard  (Timeline button click)
        │
        ▼
TimelineModal  ─ open ─→  useTimelineStore.load(owner, repo, pr, prState)
                                       │
                                       ▼
                          GET /api/repos/:o/:r/prs/:n/timeline[?refresh=true]
                                       │
                                       ▼
                      timeline_service.get_timeline()
                      ├─ TimelineCacheDB.get_cached() ── hit & fresh → return
                      ├─ cache stale or miss → gh api issues/{n}/timeline (paginated)
                      ├─ normalize events
                      ├─ TimelineCacheDB.save_cache()
                      └─ return { events, pr_state, last_updated, cached, stale, refreshing }
                                       │
                                       ▼
              TimelineView renders vertical rail + Framer-Motion event rows
                                       │
                                       ▼
    While modal open AND pr_state == OPEN:
      - poll every 45 s (force refresh)
      - show "Updated X ago · refreshing…" indicator during fetch
```

### 2.1 Reused patterns from the existing codebase

- **SQLite cache class** mirroring `LifecycleCacheDB` and `WorkflowCacheDB` in `backend/database/cache_stores.py`.
- **Service** mirroring `lifecycle_service.py` in `backend/services/`.
- **Blueprint route** added to the existing `pr_bp` in `backend/routes/pr_routes.py`.
- **Zustand store** in `frontend/src/stores/`.
- **Cache metadata fields** (`last_updated`, `cached`, `stale`, `refreshing`) already standardized across other endpoints.
- **Modal pattern** mirroring `DescriptionModal.tsx` (focus trap, esc-to-close, overlay).

## 3. Backend

### 3.1 API endpoint

Added to `backend/routes/pr_routes.py`:

```
GET /api/repos/<owner>/<repo>/prs/<pr_number>/timeline
  Query params:
    refresh=true   — force bypass cache and refetch from GitHub

  Response 200:
    {
      "events": [ TimelineEvent, ... ],
      "pr_state": "OPEN" | "CLOSED" | "MERGED",
      "last_updated": "2026-04-16T14:02:11Z",
      "cached": true,
      "stale": false,
      "refreshing": false
    }

  Response 404:  { "error": "PR not found" }
  Response 500:  { "error": "<message>" }  (falls back to stale cache if available)
```

### 3.2 Service

New module `backend/services/timeline_service.py`:

```python
def fetch_pr_timeline(owner, repo, pr_number) -> list[TimelineEvent]:
    """Paginated fetch of GitHub's issue timeline endpoint.
    Uses: gh api repos/{owner}/{repo}/issues/{pr_number}/timeline --paginate
    Normalizes raw GitHub event shapes into unified TimelineEvent dicts.
    Synthesizes an "opened" event from the PR's createdAt + author as the first element.
    """

def get_timeline(owner, repo, pr_number, force_refresh=False) -> dict:
    """Cache-aware entry point called by the route.
    - Closed/Merged PRs are immutable: cache forever.
    - Open PRs: 5-minute TTL; stale-while-revalidate returns stale immediately
      (with stale=true, refreshing=true) and launches a daemon threading.Thread
      to refetch + update the cache in the background (matching the pattern used
      by workflow_service's background refresh).
    - force_refresh=True bypasses the cache entirely.
    """
```

### 3.3 Cache DB class

New class in `backend/database/cache_stores.py`:

```python
class TimelineCacheDB(Database):
    def get_cached(self, repo, pr_number) -> dict | None
    def save_cache(self, repo, pr_number, pr_state, events) -> None
    def is_stale(self, row, ttl_minutes: int | None) -> bool
        # Returns False when ttl_minutes is None (terminal PRs never go stale)
    def clear(self) -> None
```

Singleton factory `get_timeline_cache_db()` added to `backend/database/__init__.py`.

### 3.4 Database schema

Added to `backend/database/base.py:_init_db()`:

```sql
CREATE TABLE IF NOT EXISTS pr_timeline_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    pr_state TEXT NOT NULL,          -- OPEN | CLOSED | MERGED
    data TEXT NOT NULL,               -- JSON array of normalized events
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(repo, pr_number)
);
```

### 3.5 Error handling

- `gh api` 404 → route returns 404 JSON.
- `gh api` rate-limit or transient error → if a cached entry exists, return it with `stale: true`; otherwise return 503 with the error message.
- All errors logged via `backend/extensions.logger`.

### 3.6 Cache invalidation

`/api/clear-cache` endpoint (in `backend/routes/cache_routes.py`) calls `TimelineCacheDB.clear()` alongside other cache clears.

## 4. Data model

### 4.1 Normalized `TimelineEvent` shape (TypeScript)

```ts
// frontend/src/api/types.ts (new exports)

type TimelineEventType =
  | 'opened'
  | 'committed'
  | 'commented'
  | 'reviewed'               // state disambiguates APPROVED | CHANGES_REQUESTED | COMMENTED
  | 'review_requested'
  | 'ready_for_review'
  | 'convert_to_draft'
  | 'closed'
  | 'reopened'
  | 'merged'
  | 'head_ref_force_pushed'

interface TimelineEventBase {
  id: string                 // stable dedupe key: `${type}-${created_at}-${actor}-${idx}`
  type: TimelineEventType
  created_at: string         // ISO 8601
  actor: { login: string, avatar_url: string } | null
}

interface OpenedEvent         extends TimelineEventBase { type: 'opened' }
interface CommittedEvent      extends TimelineEventBase { type: 'committed', sha: string, short_sha: string, message: string }
interface CommentedEvent      extends TimelineEventBase { type: 'commented', body: string, html_url: string }
interface ReviewedEvent       extends TimelineEventBase { type: 'reviewed', state: 'APPROVED'|'CHANGES_REQUESTED'|'COMMENTED', body: string, html_url: string }
interface ReviewRequestedEvent extends TimelineEventBase { type: 'review_requested', requested_reviewer: { login: string, avatar_url: string } }
interface ReadyForReviewEvent extends TimelineEventBase { type: 'ready_for_review' }
interface ConvertToDraftEvent extends TimelineEventBase { type: 'convert_to_draft' }
interface ClosedEvent         extends TimelineEventBase { type: 'closed' }
interface ReopenedEvent       extends TimelineEventBase { type: 'reopened' }
interface MergedEvent         extends TimelineEventBase { type: 'merged', sha: string }
interface ForcePushedEvent    extends TimelineEventBase { type: 'head_ref_force_pushed', before: string, after: string }

type TimelineEvent =
  | OpenedEvent | CommittedEvent | CommentedEvent | ReviewedEvent
  | ReviewRequestedEvent | ReadyForReviewEvent | ConvertToDraftEvent
  | ClosedEvent | ReopenedEvent | MergedEvent | ForcePushedEvent
```

### 4.2 Normalization rules in the backend service

- Commits: the GitHub timeline returns one `committed` event per commit; preserve granularity.
- `commented` events merge in from `--paginate`'s handling of issue comments in the timeline stream.
- `reviewed` events may have empty `body`; UI treats empty as "approved without comment" visually.
- `opened` is synthesized from the PR's `createdAt` + `user` (the REST timeline omits it).
- Events returned sorted ascending by `created_at`.

## 5. Frontend

### 5.1 New files

| Path | Responsibility |
|------|----------------|
| `frontend/src/api/timeline.ts` | Typed fetcher `fetchTimeline(owner, repo, prNumber, opts)` |
| `frontend/src/stores/useTimelineStore.ts` | Modal state, per-PR timeline cache, polling lifecycle, expand/filter state |
| `frontend/src/components/timeline/TimelineModal.tsx` | Full-screen modal shell (overlay, focus trap, esc-to-close) |
| `frontend/src/components/timeline/TimelineHeader.tsx` | PR title + link, refresh button, cache timestamp, close |
| `frontend/src/components/timeline/TimelineFilters.tsx` | Event-type filter chips |
| `frontend/src/components/timeline/TimelineView.tsx` | Vertical rail, stagger-in animation, event mapping |
| `frontend/src/components/timeline/TimelineEventRow.tsx` | Card shell: dot + header + expand button + body dispatcher |
| `frontend/src/components/timeline/eventBodies/CommitBody.tsx` | Commit message + SHA link |
| `frontend/src/components/timeline/eventBodies/CommentBody.tsx` | Markdown body (react-markdown + remark-gfm + rehype-highlight) |
| `frontend/src/components/timeline/eventBodies/ReviewBody.tsx` | Markdown body + review state badge |
| `frontend/src/components/timeline/eventBodies/StateChangeBody.tsx` | Generic body for closed / reopened / merged / ready_for_review / convert_to_draft |
| `frontend/src/components/timeline/eventBodies/ForcePushBody.tsx` | before/after short SHAs |
| `frontend/src/components/timeline/eventBodies/ReviewRequestedBody.tsx` | Requested reviewer info |
| `frontend/src/styles/timeline.css` | Timeline-specific CSS using Matrix UI tokens |

### 5.2 New dependency

- `framer-motion` (~55 kB gz) added to `frontend/package.json`.

### 5.3 Modified files

- `frontend/src/api/types.ts` — add `TimelineEvent` union and related types.
- `frontend/src/components/prs/PRCard.tsx` — add Timeline button to `.mx-pr-card__actions`.
- `frontend/src/components/queue/QueueItem.tsx` — add Timeline button.
- `frontend/src/App.tsx` — mount `<TimelineModal />` once at app root.

### 5.4 Zustand store shape

```ts
interface TimelineState {
  // Keyed by `${owner}/${repo}/${pr_number}`
  timelines: Record<string, {
    events: TimelineEvent[]
    prState: 'OPEN' | 'CLOSED' | 'MERGED'
    lastUpdated: string
    loading: boolean
    refreshing: boolean
    error: string | null
    expandedIds: Set<string>            // multi-expand: any number of events can be open
    hiddenTypes: Set<TimelineEventType> // filter chips
    pollTimer: number | null            // setInterval handle
  }>

  openFor: {
    owner: string; repo: string; prNumber: number; title: string; url: string
  } | null

  open(params): void
  close(): void
  load(owner, repo, prNumber, opts?: { force?: boolean }): Promise<void>
  toggleExpanded(key: string, eventId: string): void
  toggleType(key: string, type: TimelineEventType): void
  resetFilters(key: string): void
  startPolling(key: string): void
  stopPolling(key: string): void
}
```

### 5.5 Polling & optimistic invalidation

- `TimelineModal` calls `startPolling(key)` on mount; cleanup calls `stopPolling`.
- Polling interval: 45 seconds, fires only when `prState === 'OPEN'`.
- Each tick calls `load({ force: true })` which sets `refreshing: true`, preserves old data until new response lands, then swaps.
- On modal `open()`: if the cached entry exists and is older than 5 minutes AND `prState === 'OPEN'`, the first `load()` is called with `force: true` (optimistic invalidation).

## 6. Visual design

### 6.1 Layout

```
┌─ Header: #847 Add caching layer  [↻ Refresh] [Updated 12s ago]  [×] ─┐
├─ Filters:  [All] [Commits] [Reviews] [Comments] [State] [Meta]     │
│                                                                      │
│   ●─── jvargas opened                         Apr 10, 2:14 PM       │
│   │                                                                  │
│   ●─── 3 commits by jvargas                   Apr 10, 2:30 PM       │
│   │    └─ [expanded] add caching layer (abc1234)                    │
│   │                                                                  │
│   ●─── 💬 alice commented                     Apr 11, 9:02 AM       │
│   │    └─ [expanded, markdown] Can we extract `fetchWithRetry`...   │
│   │                                                                  │
│   ●─── ❌ bob requested changes               Apr 11, 3:45 PM       │
│   │                                                                  │
│   ●─── 🎉 Merged to main                      Apr 12, 10:20 AM      │
└──────────────────────────────────────────────────────────────────────┘
```

Modal is 95 vw × 95 vh on desktop; full-screen under 768 px. Event cards stack with reduced padding on mobile; filter chips wrap.

### 6.2 Color tokens

| Event type | Dot color | Matrix UI token |
|------------|-----------|-----------------|
| opened | indigo (#6366f1) | `--mx-color-accent` |
| committed | emerald (#10b981) | `--mx-color-success` |
| commented | amber (#f59e0b) | `--mx-color-warning` |
| reviewed (APPROVED) | emerald | `--mx-color-success` |
| reviewed (CHANGES_REQUESTED) | red (#ef4444) | `--mx-color-danger` |
| reviewed (COMMENTED) | amber | `--mx-color-warning` |
| review_requested | slate | `--mx-color-muted` |
| ready_for_review / convert_to_draft | sky | `--mx-color-info` |
| closed | red | `--mx-color-danger` |
| reopened | indigo | `--mx-color-accent` |
| merged | violet (#8b5cf6) | new `--mx-color-merged` |
| head_ref_force_pushed | amber | `--mx-color-warning` |

Dots use a glow ring: `box-shadow: 0 0 0 4px rgba(<color>, 0.2)`. Vertical rail is a gradient: `linear-gradient(180deg, accent → muted → transparent)`.

### 6.3 Framer Motion behaviors

1. **Stagger-in on modal open** — events fade + slide from below; 40 ms stagger; only applied to the first 20 events (the rest mount instantly when scrolled into view).
2. **Expand/collapse** — `AnimatePresence` + `motion.div` with `layout`; spring `{ type: 'spring', damping: 26, stiffness: 300 }`.
3. **Dot hover** — scale 1.0 → 1.15 with spring.
4. **Filter chip toggle** — animate width + opacity when event types hide/show.
5. **Refreshing indicator** — timestamp chip pulses opacity while `refreshing === true`.

### 6.4 Empty / loading / error states

- **Loading**: 5 ghost rows (skeleton shimmer).
- **Empty (filters hide everything)**: "No events match the selected filters" + "Reset filters" button.
- **Empty (no events at all — very rare)**: "No events yet."
- **Error**: inline card with error message + "Retry" button.

### 6.5 Accessibility

- Modal uses focus trap matching `DescriptionModal`'s pattern.
- Expand toggles are `<button>` elements with `aria-expanded`.
- Filter chips are `<button role="switch" aria-checked>`.
- Event bodies rendered via `react-markdown` (no raw HTML, XSS-safe by default).

## 7. Phased implementation

### Phase 1 — Backend foundation (PR-mergeable on its own)

1. Add `pr_timeline_cache` schema to `backend/database/base.py:_init_db()`.
2. Create `TimelineCacheDB` in `backend/database/cache_stores.py`.
3. Register `get_timeline_cache_db()` singleton in `backend/database/__init__.py`.
4. Create `backend/services/timeline_service.py` with `fetch_pr_timeline()` + `get_timeline()`.
5. Add `GET /api/repos/<owner>/<repo>/prs/<pr_number>/timeline` to `backend/routes/pr_routes.py`.
6. Wire `TimelineCacheDB.clear()` into `/api/clear-cache`.
7. Unit test: `backend/tests/test_timeline_service.py` covering the event-normalization shape.
8. Update `docs/DESIGN.md`: new endpoint, service, DB class, schema.
9. Smoke test: `curl` against a known PR; verify cache hit on second call; verify force-refresh bypass.

### Phase 2 — Frontend modal & rendering (depends on Phase 1)

1. Add `framer-motion` to `frontend/package.json`.
2. Add `TimelineEvent` union + related types to `frontend/src/api/types.ts`.
3. Create `frontend/src/api/timeline.ts`.
4. Create `frontend/src/stores/useTimelineStore.ts` (no polling yet).
5. Create `frontend/src/components/timeline/` with modal, header, filters, view, event row, and body renderers.
6. Create `frontend/src/styles/timeline.css`.
7. Add Timeline button to `PRCard.tsx`.
8. Mount `<TimelineModal />` in `App.tsx`.
9. Update `docs/DESIGN.md`: new frontend components, button, modal pattern.
10. Manual verification: open timeline for PRs with diverse events; verify each type renders; verify markdown in comments and reviews; verify filter chips; verify keyboard nav and esc-to-close.

### Phase 3 — Live updates & merge queue integration (depends on Phase 2)

1. Add polling lifecycle (`startPolling` / `stopPolling`) to `useTimelineStore`.
2. Add optimistic invalidation in `open()`.
3. Integrate `CacheTimestamp` component (or inline equivalent) showing "Updated X ago · refreshing…".
4. Add Timeline button to `frontend/src/components/queue/QueueItem.tsx`.
5. Update `docs/DESIGN.md`: polling, merge queue integration.
6. Manual verification: leave modal open on an active PR; post a comment on GitHub; verify it appears within 45 s. Close and reopen after > 10 min; verify optimistic refresh fires.

## 8. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| GitHub API rate limits | SQLite cache + stale-while-revalidate; polling only while modal open; 45 s interval |
| Large timelines (500+ events) | Stagger-in limited to first 20; Framer Motion `layout` is O(n); virtualization deferred unless perf shows issue |
| Markdown XSS in comments/reviews | `react-markdown` sanitizes by default; no `allowDangerousHtml` |
| Cache grows unbounded | SQLite is fine with thousands of cached rows; `/api/clear-cache` resets; closed PRs never grow stale so no bloat from re-fetching |
| `gh` returns partial pages on rate-limit | Service returns stale cache with `stale: true` flag; UI shows warning |

## 9. Testing strategy

- **Backend unit test** covering normalization of each event type (`test_timeline_service.py` using a fixture of a raw `gh api` response).
- **Backend smoke test** via `curl` on a real PR in Phase 1.
- **Frontend** — no formal test infra in this project per `CLAUDE.md`; verification is manual via `python app.py` + `cd frontend && npm run dev` with a checklist per phase.

## 10. Out-of-scope / future enhancements

- Horizontal mini-scrubber for long timelines (would layer cleanly on top of this design if needed later).
- Timeline views for GitHub issues.
- Keyboard shortcuts for expand/collapse/navigate (real `<button>` elements already make this easy to add).
- Bundle-level code splitting for the timeline module (defer until bundle size analysis shows need).
