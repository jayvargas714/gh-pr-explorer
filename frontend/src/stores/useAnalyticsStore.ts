import { create } from 'zustand'
import { AnalyticsDailyResponse } from '../api/types'
import { AnalyticsWindow, YMode, MetricKey, TEAM_ID } from '../utils/analyticsSeries'

interface AnalyticsState {
  // ==========================================================================
  // Daily rollup
  // ==========================================================================
  window: AnalyticsWindow
  base: string
  setWindow: (w: AnalyticsWindow) => void
  setBase: (b: string) => void

  daily: AnalyticsDailyResponse | null
  dailyKey: string | null
  dailyLoading: boolean
  dailyError: string | null
  setDaily: (d: AnalyticsDailyResponse, key: string) => void
  setDailyLoading: (loading: boolean) => void
  setDailyError: (error: string | null) => void
  resetForRepo: () => void

  statsView: 'table' | 'series'
  statsSortBy: string
  statsSortDirection: 'asc' | 'desc'
  statsYMode: YMode
  statsMetrics: MetricKey[]
  statsPeople: string[]
  setStatsView: (view: 'table' | 'series') => void
  sortStats: (column: string) => void
  setStatsYMode: (mode: YMode) => void
  toggleStatsMetric: (m: MetricKey) => void
  toggleStatsPerson: (id: string) => void

  contribMetric: 'commits' | 'additions' | 'deletions' | 'prs_merged' | 'reviews'
  setContribMetric: (metric: 'commits' | 'additions' | 'deletions' | 'prs_merged' | 'reviews') => void
}

export const useAnalyticsStore = create<AnalyticsState>((set) => ({
  // ==========================================================================
  // Daily rollup
  // ==========================================================================
  window: { preset: '3m', from: '', to: '' },
  base: 'main',
  setWindow: (w) => set({ window: w }),
  setBase: (b) => set({ base: b }),

  daily: null,
  dailyKey: null,
  dailyLoading: false,
  dailyError: null,
  setDaily: (d, key) => set({ daily: d, dailyKey: key }),
  setDailyLoading: (loading) => set({ dailyLoading: loading }),
  setDailyError: (error) => set({ dailyError: error }),
  resetForRepo: () => set({ daily: null, dailyKey: null, dailyError: null, base: 'main' }),

  statsView: 'table',
  statsSortBy: 'commits',
  statsSortDirection: 'desc',
  statsYMode: 'daily',
  statsMetrics: ['prs_merged'],
  statsPeople: [TEAM_ID],
  setStatsView: (view) => set({ statsView: view }),
  sortStats: (column) =>
    set((state) => ({
      statsSortBy: column,
      statsSortDirection:
        state.statsSortBy === column && state.statsSortDirection === 'desc'
          ? 'asc'
          : 'desc',
    })),
  setStatsYMode: (mode) => set({ statsYMode: mode }),
  toggleStatsMetric: (m) =>
    set((state) => {
      const has = state.statsMetrics.includes(m)
      if (has) {
        if (state.statsMetrics.length <= 1) return {}
        return { statsMetrics: state.statsMetrics.filter((x) => x !== m) }
      }
      return { statsMetrics: [...state.statsMetrics, m] }
    }),
  toggleStatsPerson: (id) =>
    set((state) => {
      const has = state.statsPeople.includes(id)
      if (has) {
        if (state.statsPeople.length <= 1) return {}
        return { statsPeople: state.statsPeople.filter((x) => x !== id) }
      }
      return { statsPeople: [...state.statsPeople, id] }
    }),

  contribMetric: 'commits',
  setContribMetric: (metric) => set({ contribMetric: metric }),
}))
