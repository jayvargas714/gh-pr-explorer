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

type CardsByLane = Record<number, MergeQueueItem[]>

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

  loadBoard: () => Promise<void>
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
}

function normalize(cardsByLane: Record<string, MergeQueueItem[]>): CardsByLane {
  const out: CardsByLane = {}
  for (const k of Object.keys(cardsByLane)) {
    out[Number(k)] = cardsByLane[k]
  }
  return out
}

export const useSwimlaneStore = create<SwimlaneState>((set, get) => ({
  lanes: [],
  cardsByLane: {},
  loading: false,
  error: null,
  lastUpdated: null,
  refreshing: false,
  pollPauseDepth: 0,

  loadBoard: async () => {
    set({ loading: true, error: null })
    try {
      const data = await fetchSwimlaneBoard()
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
