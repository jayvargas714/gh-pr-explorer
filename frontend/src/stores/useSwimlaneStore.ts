import { create } from 'zustand'
import { MergeQueueItem, Swimlane, SwimlaneColor } from '../api/types'
import {
  createSwimlane,
  deleteSwimlane,
  fetchSwimlaneBoard,
  moveSwimlaneCard,
  patchSwimlane,
  reorderSwimlanes,
} from '../api/swimlanes'
import { removeFromQueue } from '../api/queue'

type CardsByLane = Record<number, MergeQueueItem[]>

// Badge filter keys grouped by visual dimension. Within a dimension, multiple
// picks are OR'd (a single card can't be both Open and Merged); across
// dimensions, the combinator is controlled by `badgeFilterMode`.
export type BadgeFilterKey =
  | 'state:open' | 'state:closed' | 'state:merged'
  | 'draft'
  | 'review:approved' | 'review:changes_requested' | 'review:review_required'
  | 'ci:success' | 'ci:failure' | 'ci:pending'
  | 'has_review' | 'score:good' | 'score:ok' | 'score:bad'
  | 'new_commits' | 'reviewers_requested' | 'followup'

type BadgeDimension =
  | 'state' | 'draft' | 'review' | 'ci' | 'review_score'
  | 'new_commits' | 'reviewers' | 'followup'

export const BADGE_DIMENSION: Record<BadgeFilterKey, BadgeDimension> = {
  'state:open': 'state',
  'state:closed': 'state',
  'state:merged': 'state',
  draft: 'draft',
  'review:approved': 'review',
  'review:changes_requested': 'review',
  'review:review_required': 'review',
  'ci:success': 'ci',
  'ci:failure': 'ci',
  'ci:pending': 'ci',
  has_review: 'review_score',
  'score:good': 'review_score',
  'score:ok': 'review_score',
  'score:bad': 'review_score',
  new_commits: 'new_commits',
  reviewers_requested: 'reviewers',
  followup: 'followup',
}

export type BadgeFilterMode = 'OR' | 'AND'

interface SwimlaneState {
  lanes: Swimlane[]
  cardsByLane: CardsByLane
  loading: boolean
  error: string | null
  // Last successful board fetch (ISO string) — drives the "Updated X ago" indicator.
  lastUpdated: string | null
  // Background poll in flight (used to pulse the freshness indicator).
  refreshing: boolean
  // Counter-based pause: incremented on drag start / mutation start, decremented on end.
  // Polling is suspended while > 0 to avoid clobbering optimistic state mid-drag.
  pollPauseDepth: number
  // Free-text search across cards (PR number, title, author, repo). Empty string = no filter.
  searchQuery: string
  setSearchQuery: (q: string) => void
  // Badge-driven visibility filter. Empty set = no filter.
  badgeFilters: Set<BadgeFilterKey>
  badgeFilterMode: BadgeFilterMode
  toggleBadgeFilter: (key: BadgeFilterKey) => void
  setBadgeFilterMode: (mode: BadgeFilterMode) => void
  clearBadgeFilters: () => void

  loadBoard: (opts?: { force?: boolean }) => Promise<void>
  refreshBoard: () => Promise<void>
  createLane: (name: string, color: SwimlaneColor) => Promise<void>
  renameLane: (id: number, name: string) => Promise<void>
  recolorLane: (id: number, color: SwimlaneColor) => Promise<void>
  deleteLane: (id: number) => Promise<void>
  reorderLanesLocal: (fromIndex: number, toIndex: number) => Promise<void>
  pausePolling: () => void
  resumePolling: () => void

  // Returns true if the move was applied successfully (or restored on failure)
  moveCard: (
    queueItemId: number,
    fromLaneId: number,
    toLaneId: number,
    toIndex: number
  ) => Promise<void>

  // Bulk-remove all cards with prState === 'MERGED' from the merge queue.
  // Returns the count of cards removed.
  clearMergedCards: () => Promise<number>
}

function normalize(cardsByLane: Record<string, MergeQueueItem[]>): CardsByLane {
  const out: CardsByLane = {}
  for (const k of Object.keys(cardsByLane)) {
    out[Number(k)] = cardsByLane[k]
  }
  return out
}

/**
 * Match a swimlane card against the search query. Matches:
 *  - exact PR number (when query is all digits)
 *  - any substring of PR number, title, author, repo (case-insensitive)
 * Empty / whitespace-only query → always false (caller decides what to do).
 */
export function cardMatchesQuery(card: MergeQueueItem, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return false
  if (/^\d+$/.test(q) && String(card.number) === q) return true
  const haystack = [
    String(card.number),
    card.title || '',
    card.author || '',
    card.repo || '',
  ]
    .join(' ')
    .toLowerCase()
  return haystack.includes(q)
}

// Per-key predicate. Field names mirror getStateBadge/getReviewStatusBadge/etc.
// in QueueItem so a filter matches exactly the cards whose badge is rendered.
function cardMatchesBadge(card: MergeQueueItem, key: BadgeFilterKey): boolean {
  switch (key) {
    case 'state:open':   return card.prState === 'OPEN'
    case 'state:closed': return card.prState === 'CLOSED'
    case 'state:merged': return card.prState === 'MERGED'
    case 'draft':        return !!card.isDraft
    case 'review:approved':          return card.reviewDecision === 'APPROVED'
    case 'review:changes_requested': return card.reviewDecision === 'CHANGES_REQUESTED'
    case 'review:review_required':   return card.reviewDecision === 'REVIEW_REQUIRED'
    case 'ci:success': return card.ciStatus === 'success'
    case 'ci:failure': return card.ciStatus === 'failure'
    case 'ci:pending': return card.ciStatus === 'pending'
    case 'has_review': return !!card.hasReview
    case 'score:good': return !!card.hasReview && card.reviewScore != null && card.reviewScore >= 7
    case 'score:ok':   return !!card.hasReview && card.reviewScore != null && card.reviewScore >= 4 && card.reviewScore <= 6
    case 'score:bad':  return !!card.hasReview && card.reviewScore != null && card.reviewScore < 4
    case 'new_commits':         return !!card.hasNewCommits
    case 'reviewers_requested': return (card.currentReviewers?.length ?? 0) > 0
    case 'followup':            return !!card.isFollowup
  }
}

/**
 * Visibility check for the badge filter. Returns true when no filters are
 * active. With multiple filters: within a dimension picks are OR'd; across
 * dimensions the combinator is `mode`.
 */
export function cardMatchesBadges(
  card: MergeQueueItem,
  filters: Set<BadgeFilterKey>,
  mode: BadgeFilterMode,
): boolean {
  if (filters.size === 0) return true
  if (mode === 'OR') {
    for (const k of filters) if (cardMatchesBadge(card, k)) return true
    return false
  }
  const byDim = new Map<BadgeDimension, BadgeFilterKey[]>()
  for (const k of filters) {
    const dim = BADGE_DIMENSION[k]
    const arr = byDim.get(dim)
    if (arr) arr.push(k)
    else byDim.set(dim, [k])
  }
  for (const keys of byDim.values()) {
    if (!keys.some((k) => cardMatchesBadge(card, k))) return false
  }
  return true
}

/**
 * Combined visibility check: a card is "matching" iff it passes the text
 * search (when active) AND the badge filter (when active). Both empty = match.
 */
export function cardPassesFilters(
  card: MergeQueueItem,
  query: string,
  badges: Set<BadgeFilterKey>,
  mode: BadgeFilterMode,
): boolean {
  const passesText = query.trim().length === 0 || cardMatchesQuery(card, query)
  if (!passesText) return false
  return cardMatchesBadges(card, badges, mode)
}

export const useSwimlaneStore = create<SwimlaneState>((set, get) => ({
  lanes: [],
  cardsByLane: {},
  loading: false,
  error: null,
  lastUpdated: null,
  refreshing: false,
  pollPauseDepth: 0,
  searchQuery: '',
  setSearchQuery: (q) => set({ searchQuery: q }),
  badgeFilters: new Set<BadgeFilterKey>(),
  badgeFilterMode: 'OR',
  toggleBadgeFilter: (key) => set((s) => {
    const next = new Set(s.badgeFilters)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    return { badgeFilters: next }
  }),
  setBadgeFilterMode: (mode) => set({ badgeFilterMode: mode }),
  clearBadgeFilters: () => set({ badgeFilters: new Set<BadgeFilterKey>() }),

  loadBoard: async (opts = {}) => {
    set({ loading: true, error: null })
    try {
      // force=true also invalidates per-PR timeline caches on the backend so
      // a subsequent timeline-modal open shows fresh events, not <=5min stale.
      const data = await fetchSwimlaneBoard({ refresh: opts.force })
      set({
        lanes: data.lanes,
        cardsByLane: normalize(data.cardsByLane),
        loading: false,
        lastUpdated: new Date().toISOString(),
      })
    } catch (e) {
      set({ error: e instanceof Error ? e.message : 'Failed to load board', loading: false })
    }
  },

  // Silent refresh: does not flip `loading`, swallows transient errors so a brief
  // network blip doesn't surface a banner during background polling. Skipped
  // entirely when polling is paused (drag in flight, modal hidden, etc.).
  refreshBoard: async () => {
    if (get().pollPauseDepth > 0) return
    set({ refreshing: true })
    try {
      const data = await fetchSwimlaneBoard()
      // Re-check pause depth: a drag may have started while the request was in
      // flight. Discard the response in that case to avoid clobbering the
      // optimistic state.
      if (get().pollPauseDepth > 0) {
        set({ refreshing: false })
        return
      }
      set({
        lanes: data.lanes,
        cardsByLane: normalize(data.cardsByLane),
        lastUpdated: new Date().toISOString(),
        refreshing: false,
      })
    } catch {
      set({ refreshing: false })
    }
  },

  pausePolling: () => set((s) => ({ pollPauseDepth: s.pollPauseDepth + 1 })),
  resumePolling: () => set((s) => ({ pollPauseDepth: Math.max(0, s.pollPauseDepth - 1) })),

  createLane: async (name, color) => {
    try {
      const { lane } = await createSwimlane(name, color)
      set((state) => ({
        lanes: [...state.lanes, lane],
        cardsByLane: { ...state.cardsByLane, [lane.id]: [] },
      }))
    } catch (e) {
      set({ error: e instanceof Error ? e.message : 'Failed to create lane' })
    }
  },

  renameLane: async (id, name) => {
    const prev = get().lanes
    set((state) => ({ lanes: state.lanes.map((l) => (l.id === id ? { ...l, name } : l)) }))
    try {
      await patchSwimlane(id, { name })
    } catch (e) {
      set({ lanes: prev, error: e instanceof Error ? e.message : 'Failed to rename lane' })
    }
  },

  recolorLane: async (id, color) => {
    const prev = get().lanes
    set((state) => ({ lanes: state.lanes.map((l) => (l.id === id ? { ...l, color } : l)) }))
    try {
      await patchSwimlane(id, { color })
    } catch (e) {
      set({ lanes: prev, error: e instanceof Error ? e.message : 'Failed to recolor lane' })
    }
  },

  deleteLane: async (id) => {
    try {
      await deleteSwimlane(id)
      // Server re-homed orphans; reload to get the truth.
      await get().loadBoard()
    } catch (e) {
      set({ error: e instanceof Error ? e.message : 'Failed to delete lane' })
    }
  },

  // Reorder only among non-default lanes; default lane stays pinned at position 1.
  reorderLanesLocal: async (fromIndex, toIndex) => {
    const prevLanes = get().lanes
    const defaultLane = prevLanes.find((l) => l.isDefault)
    const others = prevLanes.filter((l) => !l.isDefault)
    if (fromIndex < 0 || fromIndex >= others.length || toIndex < 0 || toIndex >= others.length) {
      return
    }
    const reordered = [...others]
    const [moved] = reordered.splice(fromIndex, 1)
    reordered.splice(toIndex, 0, moved)
    const next = defaultLane ? [defaultLane, ...reordered] : reordered
    set({ lanes: next.map((l, i) => ({ ...l, position: i + 1 })) })
    get().pausePolling()
    try {
      await reorderSwimlanes(next.map((l) => l.id))
    } catch (e) {
      set({ lanes: prevLanes, error: e instanceof Error ? e.message : 'Failed to reorder lanes' })
    } finally {
      get().resumePolling()
    }
  },

  clearMergedCards: async () => {
    const merged: MergeQueueItem[] = []
    for (const list of Object.values(get().cardsByLane)) {
      for (const c of list) if (c.prState === 'MERGED') merged.push(c)
    }
    if (merged.length === 0) return 0
    get().pausePolling()
    try {
      await Promise.all(merged.map((c) => removeFromQueue(c.number, c.repo).catch(() => null)))
      await get().loadBoard()
    } finally {
      get().resumePolling()
    }
    return merged.length
  },

  moveCard: async (queueItemId, fromLaneId, toLaneId, toIndex) => {
    const prev = get().cardsByLane

    const next: CardsByLane = {}
    for (const k of Object.keys(prev)) next[Number(k)] = [...prev[Number(k)]]

    const fromList = next[fromLaneId] ?? []
    const cardIndex = fromList.findIndex((c) => c.id === queueItemId)
    if (cardIndex === -1) return
    const [card] = fromList.splice(cardIndex, 1)
    next[fromLaneId] = fromList

    const toList = next[toLaneId] ?? []
    const clampedIndex = Math.max(0, Math.min(toIndex, toList.length))
    toList.splice(clampedIndex, 0, card)
    next[toLaneId] = toList

    set({ cardsByLane: next })

    get().pausePolling()
    try {
      await moveSwimlaneCard(queueItemId, toLaneId, clampedIndex + 1)
    } catch (e) {
      set({ cardsByLane: prev, error: e instanceof Error ? e.message : 'Failed to move card' })
    } finally {
      get().resumePolling()
    }
  },
}))
