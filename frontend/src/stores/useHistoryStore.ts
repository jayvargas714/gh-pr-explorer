import { create } from 'zustand'
import { ReviewHistoryItem, ReviewStats } from '../api/types'

interface HistoryState {
  // Review history
  reviews: ReviewHistoryItem[]
  totalReviews: number
  loading: boolean
  error: string | null

  // Filters
  searchQuery: string
  repoFilter: string
  authorFilter: string
  prNumberFilter: string
  dateRangeStart: string
  dateRangeEnd: string
  scoreMin: number | null
  scoreMax: number | null

  // Sorting & Pagination
  sortBy: string
  sortDirection: 'asc' | 'desc'
  currentPage: number
  reviewsPerPage: number

  // Stats
  reviewStats: ReviewStats | null

  // Actions
  setReviews: (reviews: ReviewHistoryItem[], total: number) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void

  setSearchQuery: (query: string) => void
  setRepoFilter: (repo: string) => void
  setAuthorFilter: (author: string) => void
  setPRNumberFilter: (prNumber: string) => void
  setDateRangeStart: (date: string) => void
  setDateRangeEnd: (date: string) => void
  setScoreRange: (min: number | null, max: number | null) => void
  resetFilters: () => void

  setSortBy: (column: string) => void
  setSortDirection: (direction: 'asc' | 'desc') => void
  setCurrentPage: (page: number) => void

  setReviewStats: (stats: ReviewStats | null) => void

  // Helpers
  getActiveFiltersCount: () => number
}

export const useHistoryStore = create<HistoryState>((set, get) => ({
  // Review history
  reviews: [],
  totalReviews: 0,
  loading: false,
  error: null,

  // Filters
  searchQuery: '',
  repoFilter: '',
  authorFilter: '',
  prNumberFilter: '',
  dateRangeStart: '',
  dateRangeEnd: '',
  scoreMin: null,
  scoreMax: null,

  // Sorting & Pagination
  sortBy: 'review_timestamp',
  sortDirection: 'desc',
  currentPage: 1,
  reviewsPerPage: 20,

  // Stats
  reviewStats: null,

  // Actions
  setReviews: (reviews, total) =>
    set({ reviews, totalReviews: total, currentPage: 1 }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),

  setSearchQuery: (query) => set({ searchQuery: query }),
  setRepoFilter: (repo) => set({ repoFilter: repo }),
  setAuthorFilter: (author) => set({ authorFilter: author }),
  setPRNumberFilter: (prNumber) => set({ prNumberFilter: prNumber }),
  setDateRangeStart: (date) => set({ dateRangeStart: date }),
  setDateRangeEnd: (date) => set({ dateRangeEnd: date }),
  setScoreRange: (min, max) => set({ scoreMin: min, scoreMax: max }),
  resetFilters: () =>
    set({
      searchQuery: '',
      repoFilter: '',
      authorFilter: '',
      prNumberFilter: '',
      dateRangeStart: '',
      dateRangeEnd: '',
      scoreMin: null,
      scoreMax: null,
    }),

  setSortBy: (column) => set({ sortBy: column }),
  setSortDirection: (direction) => set({ sortDirection: direction }),
  setCurrentPage: (page) => set({ currentPage: page }),

  setReviewStats: (stats) => set({ reviewStats: stats }),

  // Helpers
  getActiveFiltersCount: () => {
    const state = get()
    let count = 0
    if (state.searchQuery) count++
    if (state.repoFilter) count++
    if (state.authorFilter) count++
    if (state.prNumberFilter) count++
    if (state.dateRangeStart) count++
    if (state.dateRangeEnd) count++
    if (state.scoreMin !== null) count++
    if (state.scoreMax !== null) count++
    return count
  },
}))
