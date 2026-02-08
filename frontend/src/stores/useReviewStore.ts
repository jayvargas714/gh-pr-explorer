import { create } from 'zustand'
import { Review } from '../api/types'

interface ReviewState {
  // Active reviews
  activeReviews: Record<string, Review>
  loading: boolean
  error: string | null

  // Polling
  pollingEnabled: boolean

  // Review error modal
  reviewErrorModal: {
    show: boolean
    prNumber: number | null
    prTitle: string
    errorOutput: string
    exitCode: number | null
  }

  // Review viewer modal
  showReviewViewer: boolean
  reviewViewerContent: {
    id: number
    content: string
    prNumber: number
    prTitle: string
    prAuthor: string
    prUrl: string
    reviewTimestamp: string
    score: number | null
  } | null

  // Copy success feedback
  copySuccess: boolean

  // Actions
  setActiveReviews: (reviews: Review[]) => void
  updateReview: (key: string, review: Review) => void
  removeReview: (key: string) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void

  setPollingEnabled: (enabled: boolean) => void

  showReviewError: (
    prNumber: number,
    prTitle: string,
    errorOutput: string,
    exitCode: number | null
  ) => void
  hideReviewError: () => void

  openReviewViewer: (content: any) => void
  closeReviewViewer: () => void

  setCopySuccess: (success: boolean) => void

  // Helpers
  getReviewStatus: (prNumber: number, owner: string, repo: string) => Review | null
  hasRunningReviews: () => boolean
}

export const useReviewStore = create<ReviewState>((set, get) => ({
  // Active reviews
  activeReviews: {},
  loading: false,
  error: null,

  // Polling
  pollingEnabled: false,

  // Review error modal
  reviewErrorModal: {
    show: false,
    prNumber: null,
    prTitle: '',
    errorOutput: '',
    exitCode: null,
  },

  // Review viewer modal
  showReviewViewer: false,
  reviewViewerContent: null,

  // Copy success feedback
  copySuccess: false,

  // Actions
  setActiveReviews: (reviews) => {
    const reviewsMap: Record<string, Review> = {}
    reviews.forEach((review) => {
      reviewsMap[review.key] = review
    })
    set({ activeReviews: reviewsMap })
  },

  updateReview: (key, review) =>
    set((state) => ({
      activeReviews: { ...state.activeReviews, [key]: review },
    })),

  removeReview: (key) =>
    set((state) => {
      const { [key]: _, ...rest } = state.activeReviews
      return { activeReviews: rest }
    }),

  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),

  setPollingEnabled: (enabled) => set({ pollingEnabled: enabled }),

  showReviewError: (prNumber, prTitle, errorOutput, exitCode) =>
    set({
      reviewErrorModal: {
        show: true,
        prNumber,
        prTitle,
        errorOutput,
        exitCode,
      },
    }),

  hideReviewError: () =>
    set({
      reviewErrorModal: {
        show: false,
        prNumber: null,
        prTitle: '',
        errorOutput: '',
        exitCode: null,
      },
    }),

  openReviewViewer: (content) =>
    set({
      showReviewViewer: true,
      reviewViewerContent: content,
    }),

  closeReviewViewer: () =>
    set({
      showReviewViewer: false,
      reviewViewerContent: null,
    }),

  setCopySuccess: (success) => set({ copySuccess: success }),

  // Helpers
  getReviewStatus: (prNumber, owner, repo) => {
    const key = `${owner}/${repo}/${prNumber}`
    return get().activeReviews[key] || null
  },

  hasRunningReviews: () => {
    const { activeReviews } = get()
    return Object.values(activeReviews).some((review) => review.status === 'running')
  },
}))
