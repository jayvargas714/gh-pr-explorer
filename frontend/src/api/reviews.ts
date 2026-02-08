import { api } from './client'
import {
  ReviewsResponse,
  ReviewHistoryResponse,
  ReviewDetail,
  ReviewStatsResponse,
  MessageResponse,
} from './types'

/**
 * Fetch active reviews
 */
export async function fetchActiveReviews(): Promise<ReviewsResponse> {
  return api.get<ReviewsResponse>('/reviews')
}

/**
 * Start a code review
 */
export async function startReview(data: {
  number: number
  url: string
  owner: string
  repo: string
  title?: string
  author?: string
  is_followup?: boolean
  previous_review_id?: number
}): Promise<{ message: string; key: string; status: string }> {
  return api.post('/reviews', data)
}

/**
 * Cancel a running review
 */
export async function cancelReview(
  owner: string,
  repo: string,
  prNumber: number
): Promise<MessageResponse> {
  return api.delete<MessageResponse>(`/reviews/${owner}/${repo}/${prNumber}`)
}

/**
 * Get review status
 */
export async function getReviewStatus(owner: string, repo: string, prNumber: number) {
  return api.get(`/reviews/${owner}/${repo}/${prNumber}/status`)
}

/**
 * Post inline comments from review
 */
export async function postInlineComments(reviewId: number): Promise<MessageResponse> {
  return api.post<MessageResponse>(`/reviews/${reviewId}/post-inline-comments`)
}

/**
 * Check if PR has new commits
 */
export async function checkNewCommits(owner: string, repo: string, prNumber: number) {
  return api.get(`/reviews/check-new-commits/${owner}/${repo}/${prNumber}`)
}

/**
 * Fetch review history with filters
 */
export async function fetchReviewHistory(params: {
  repo?: string
  author?: string
  pr_number?: number
  search?: string
  limit?: number
  offset?: number
}): Promise<ReviewHistoryResponse> {
  const queryParams = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      queryParams.append(key, String(value))
    }
  })

  const queryString = queryParams.toString()
  return api.get<ReviewHistoryResponse>(
    `/review-history${queryString ? `?${queryString}` : ''}`
  )
}

/**
 * Get review detail by ID
 */
export async function getReviewDetail(reviewId: number): Promise<ReviewDetail> {
  const response = await api.get<{ review: ReviewDetail }>(
    `/review-history/${reviewId}`
  )
  return response.review
}

/**
 * Get reviews for a specific PR
 */
export async function getPRReviews(owner: string, repo: string, prNumber: number) {
  return api.get(`/review-history/pr/${owner}/${repo}/${prNumber}`)
}

/**
 * Get review statistics
 */
export async function getReviewStats(): Promise<ReviewStatsResponse> {
  return api.get<ReviewStatsResponse>('/review-history/stats')
}

/**
 * Check if PR has been reviewed
 */
export async function checkPRReviewed(owner: string, repo: string, prNumber: number) {
  return api.get(`/review-history/check/${owner}/${repo}/${prNumber}`)
}
