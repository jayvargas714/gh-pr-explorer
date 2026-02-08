import { create } from 'zustand'
import {
  DeveloperStats,
  CodeActivity,
  LifecycleMetrics,
  ReviewResponsiveness,
} from '../api/types'

interface AnalyticsState {
  // Developer stats
  developerStats: DeveloperStats[]
  statsLoading: boolean
  statsError: string | null
  statsSortBy: string
  statsSortDirection: 'asc' | 'desc'

  // Code activity
  codeActivity: CodeActivity | null
  activityLoading: boolean
  activityError: string | null
  activityTimeframe: number

  // Lifecycle metrics
  lifecycleMetrics: LifecycleMetrics | null
  lifecycleLoading: boolean
  lifecycleError: string | null
  lifecycleSortBy: string
  lifecycleSortDirection: 'asc' | 'desc'

  // Review responsiveness
  reviewResponsiveness: ReviewResponsiveness | null
  responsivenessLoading: boolean
  responsivenessError: string | null
  responsivenessSortBy: string
  responsivenessSortDirection: 'asc' | 'desc'

  // Actions
  setDeveloperStats: (stats: DeveloperStats[]) => void
  setStatsLoading: (loading: boolean) => void
  setStatsError: (error: string | null) => void
  sortStats: (column: string) => void

  setCodeActivity: (activity: CodeActivity | null) => void
  setActivityLoading: (loading: boolean) => void
  setActivityError: (error: string | null) => void
  setActivityTimeframe: (timeframe: number) => void

  setLifecycleMetrics: (metrics: LifecycleMetrics | null) => void
  setLifecycleLoading: (loading: boolean) => void
  setLifecycleError: (error: string | null) => void
  sortLifecycle: (column: string) => void

  setReviewResponsiveness: (responsiveness: ReviewResponsiveness | null) => void
  setResponsivenessLoading: (loading: boolean) => void
  setResponsivenessError: (error: string | null) => void
  sortResponsiveness: (column: string) => void

  // Computed
  getSortedStats: () => DeveloperStats[]
  getSortedLifecyclePRs: () => any[]
  getSortedReviewerLeaderboard: () => any[]
}

export const useAnalyticsStore = create<AnalyticsState>((set, get) => ({
  // Developer stats
  developerStats: [],
  statsLoading: false,
  statsError: null,
  statsSortBy: 'commits',
  statsSortDirection: 'desc',

  // Code activity
  codeActivity: null,
  activityLoading: false,
  activityError: null,
  activityTimeframe: 52,

  // Lifecycle metrics
  lifecycleMetrics: null,
  lifecycleLoading: false,
  lifecycleError: null,
  lifecycleSortBy: '',
  lifecycleSortDirection: 'desc',

  // Review responsiveness
  reviewResponsiveness: null,
  responsivenessLoading: false,
  responsivenessError: null,
  responsivenessSortBy: '',
  responsivenessSortDirection: 'desc',

  // Actions
  setDeveloperStats: (stats) => set({ developerStats: stats }),
  setStatsLoading: (loading) => set({ statsLoading: loading }),
  setStatsError: (error) => set({ statsError: error }),
  sortStats: (column) =>
    set((state) => ({
      statsSortBy: column,
      statsSortDirection:
        state.statsSortBy === column && state.statsSortDirection === 'desc'
          ? 'asc'
          : 'desc',
    })),

  setCodeActivity: (activity) => set({ codeActivity: activity }),
  setActivityLoading: (loading) => set({ activityLoading: loading }),
  setActivityError: (error) => set({ activityError: error }),
  setActivityTimeframe: (timeframe) => set({ activityTimeframe: timeframe }),

  setLifecycleMetrics: (metrics) => set({ lifecycleMetrics: metrics }),
  setLifecycleLoading: (loading) => set({ lifecycleLoading: loading }),
  setLifecycleError: (error) => set({ lifecycleError: error }),
  sortLifecycle: (column) =>
    set((state) => ({
      lifecycleSortBy: column,
      lifecycleSortDirection:
        state.lifecycleSortBy === column && state.lifecycleSortDirection === 'desc'
          ? 'asc'
          : 'desc',
    })),

  setReviewResponsiveness: (responsiveness) =>
    set({ reviewResponsiveness: responsiveness }),
  setResponsivenessLoading: (loading) => set({ responsivenessLoading: loading }),
  setResponsivenessError: (error) => set({ responsivenessError: error }),
  sortResponsiveness: (column) =>
    set((state) => ({
      responsivenessSortBy: column,
      responsivenessSortDirection:
        state.responsivenessSortBy === column &&
        state.responsivenessSortDirection === 'desc'
          ? 'asc'
          : 'desc',
    })),

  // Computed
  getSortedStats: () => {
    const { developerStats, statsSortBy, statsSortDirection } = get()
    if (!statsSortBy) return developerStats

    return [...developerStats].sort((a, b) => {
      const aVal = (a as any)[statsSortBy] || 0
      const bVal = (b as any)[statsSortBy] || 0
      return statsSortDirection === 'asc' ? aVal - bVal : bVal - aVal
    })
  },

  getSortedLifecyclePRs: () => {
    const { lifecycleMetrics, lifecycleSortBy, lifecycleSortDirection } = get()
    if (!lifecycleMetrics || !lifecycleSortBy) return lifecycleMetrics?.pr_table || []

    return [...lifecycleMetrics.pr_table].sort((a, b) => {
      const aVal = (a as any)[lifecycleSortBy]
      const bVal = (b as any)[lifecycleSortBy]

      // Handle nulls
      if (aVal === null && bVal === null) return 0
      if (aVal === null) return 1
      if (bVal === null) return -1

      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return lifecycleSortDirection === 'asc' ? aVal - bVal : bVal - aVal
      }
      return lifecycleSortDirection === 'asc'
        ? String(aVal).localeCompare(String(bVal))
        : String(bVal).localeCompare(String(aVal))
    })
  },

  getSortedReviewerLeaderboard: () => {
    const {
      reviewResponsiveness,
      responsivenessSortBy,
      responsivenessSortDirection,
    } = get()
    if (!reviewResponsiveness || !responsivenessSortBy)
      return reviewResponsiveness?.leaderboard || []

    return [...reviewResponsiveness.leaderboard].sort((a, b) => {
      const aVal = (a as any)[responsivenessSortBy] || 0
      const bVal = (b as any)[responsivenessSortBy] || 0
      return responsivenessSortDirection === 'asc' ? aVal - bVal : bVal - aVal
    })
  },
}))
