import { create } from 'zustand'
import { MergeQueueItem, QueueNote } from '../api/types'

interface QueueState {
  // Queue
  mergeQueue: MergeQueueItem[]
  loading: boolean
  error: string | null

  // Notes
  notesCache: Record<number, QueueNote[]>

  // Actions
  setMergeQueue: (queue: MergeQueueItem[]) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void

  addToQueue: (item: MergeQueueItem) => void
  removeFromQueue: (prNumber: number, repo: string) => void
  reorderQueue: (fromIndex: number, toIndex: number) => void

  setNotes: (itemId: number, notes: QueueNote[]) => void
  addNote: (itemId: number, note: QueueNote) => void
  removeNote: (itemId: number, noteId: number) => void

  // Helpers
  isInQueue: (prNumber: number, repo: string) => boolean
  getQueueCount: () => number
}

export const useQueueStore = create<QueueState>((set, get) => ({
  // Queue
  mergeQueue: [],
  loading: false,
  error: null,

  // Notes
  notesCache: {},

  // Actions
  setMergeQueue: (queue) => set({ mergeQueue: queue }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),

  addToQueue: (item) =>
    set((state) => ({ mergeQueue: [...state.mergeQueue, item] })),

  removeFromQueue: (prNumber, repo) =>
    set((state) => ({
      mergeQueue: state.mergeQueue.filter(
        (item) => !(item.number === prNumber && item.repo === repo)
      ),
    })),

  reorderQueue: (fromIndex, toIndex) =>
    set((state) => {
      const newQueue = [...state.mergeQueue]
      const [removed] = newQueue.splice(fromIndex, 1)
      newQueue.splice(toIndex, 0, removed)
      return { mergeQueue: newQueue }
    }),

  setNotes: (itemId, notes) =>
    set((state) => ({
      notesCache: { ...state.notesCache, [itemId]: notes },
    })),

  addNote: (itemId, note) =>
    set((state) => ({
      notesCache: {
        ...state.notesCache,
        [itemId]: [...(state.notesCache[itemId] || []), note],
      },
    })),

  removeNote: (itemId, noteId) =>
    set((state) => ({
      notesCache: {
        ...state.notesCache,
        [itemId]: (state.notesCache[itemId] || []).filter((n) => n.id !== noteId),
      },
    })),

  // Helpers
  isInQueue: (prNumber, repo) => {
    const { mergeQueue } = get()
    return mergeQueue.some((item) => item.number === prNumber && item.repo === repo)
  },

  getQueueCount: () => get().mergeQueue.length,
}))
