import { create } from 'zustand'
import { PullRequest, DivergenceMap } from '../api/types'

export interface PRReviewInfo {
  reviewId: number
  score: number | null
}

interface PRState {
  // PRs
  prs: PullRequest[]
  loading: boolean
  error: string | null

  // Pagination
  currentPage: number
  prsPerPage: number

  // Divergence
  prDivergence: DivergenceMap
  divergenceLoading: boolean

  // Review scores (pr_number -> review info)
  prReviewScores: Record<number, PRReviewInfo>

  // Actions
  setPRs: (prs: PullRequest[]) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  setCurrentPage: (page: number) => void
  setPRDivergence: (divergence: DivergenceMap) => void
  setDivergenceLoading: (loading: boolean) => void
  setPRReviewScores: (scores: Record<number, PRReviewInfo>) => void

  // Computed
  getPaginatedPRs: () => PullRequest[]
  getTotalPages: () => number
}

export const usePRStore = create<PRState>((set, get) => ({
  // PRs
  prs: [],
  loading: false,
  error: null,

  // Pagination
  currentPage: 1,
  prsPerPage: 20,

  // Divergence
  prDivergence: {},
  divergenceLoading: false,

  // Review scores
  prReviewScores: {},

  // Actions
  setPRs: (prs) => set({ prs, currentPage: 1 }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
  setCurrentPage: (page) => set({ currentPage: page }),
  setPRDivergence: (divergence) => set({ prDivergence: divergence }),
  setDivergenceLoading: (loading) => set({ divergenceLoading: loading }),
  setPRReviewScores: (scores) => set({ prReviewScores: scores }),

  // Computed
  getPaginatedPRs: () => {
    const { prs, currentPage, prsPerPage } = get()
    const startIndex = (currentPage - 1) * prsPerPage
    const endIndex = startIndex + prsPerPage
    return prs.slice(startIndex, endIndex)
  },

  getTotalPages: () => {
    const { prs, prsPerPage } = get()
    return Math.ceil(prs.length / prsPerPage)
  },
}))
