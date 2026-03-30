import { create } from 'zustand'
import type { RepoStats, LOCResult, CacheMeta } from '../api/types'

interface RepoStatsState {
  repoStats: RepoStats | null
  loading: boolean
  error: string | null

  locResult: LOCResult | null
  locLoading: boolean
  locError: string | null

  cacheMeta: CacheMeta

  setRepoStats: (stats: RepoStats | null) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void

  setLOCResult: (result: LOCResult | null) => void
  setLOCLoading: (loading: boolean) => void
  setLOCError: (error: string | null) => void

  setCacheMeta: (meta: Partial<CacheMeta>) => void

  reset: () => void
}

const initialCacheMeta: CacheMeta = {
  last_updated: null,
  cached: false,
  stale: false,
  refreshing: false,
}

export const useRepoStatsStore = create<RepoStatsState>((set) => ({
  repoStats: null,
  loading: false,
  error: null,

  locResult: null,
  locLoading: false,
  locError: null,

  cacheMeta: { ...initialCacheMeta },

  setRepoStats: (stats) => set({ repoStats: stats }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),

  setLOCResult: (result) => set({ locResult: result }),
  setLOCLoading: (loading) => set({ locLoading: loading }),
  setLOCError: (error) => set({ locError: error }),

  setCacheMeta: (meta) => set((state) => ({ cacheMeta: { ...state.cacheMeta, ...meta } })),

  reset: () => set({
    repoStats: null,
    loading: false,
    error: null,
    locResult: null,
    locLoading: false,
    locError: null,
    cacheMeta: { ...initialCacheMeta },
  }),
}))
