import { api } from './client'
import { ReviewLogsResponse, ReviewLogStatsResponse } from './types'

function queryString(filters: Record<string, unknown>): string {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      params.append(key, String(value))
    }
  })
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

/**
 * Fetch review lifecycle events, newest first.
 */
export async function fetchReviewLogs(
  filters: {
    repo?: string
    pr_number?: number
    event?: string
    reason?: string
    since?: string
    limit?: number
    offset?: number
  } = {}
): Promise<ReviewLogsResponse> {
  return api.get<ReviewLogsResponse>(`/review-logs${queryString(filters)}`)
}

/**
 * Fetch aggregate counts for the Review Logs summary strip.
 */
export async function fetchReviewLogStats(
  filters: { repo?: string; since?: string } = {}
): Promise<ReviewLogStatsResponse> {
  return api.get<ReviewLogStatsResponse>(`/review-logs/stats${queryString(filters)}`)
}
