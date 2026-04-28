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

  loadBoard: () => Promise<void>
  createLane: (name: string, color: SwimlaneColor) => Promise<void>
  renameLane: (id: number, name: string) => Promise<void>
  recolorLane: (id: number, color: SwimlaneColor) => Promise<void>
  deleteLane: (id: number) => Promise<void>
  reorderLanesLocal: (fromIndex: number, toIndex: number) => Promise<void>

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

  loadBoard: async () => {
    set({ loading: true, error: null })
    try {
      const data = await fetchSwimlaneBoard()
      set({ lanes: data.lanes, cardsByLane: normalize(data.cardsByLane), loading: false })
    } catch (e) {
      set({ error: e instanceof Error ? e.message : 'Failed to load board', loading: false })
    }
  },

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
    try {
      await reorderSwimlanes(next.map((l) => l.id))
    } catch (e) {
      set({ lanes: prevLanes, error: e instanceof Error ? e.message : 'Failed to reorder lanes' })
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

    try {
      await moveSwimlaneCard(queueItemId, toLaneId, clampedIndex + 1)
    } catch (e) {
      set({ cardsByLane: prev, error: e instanceof Error ? e.message : 'Failed to move card' })
    }
  },
}))
