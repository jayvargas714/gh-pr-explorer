import { api } from './client'
import {
  StatsResponse,
  CodeActivityResponse,
  LifecycleMetricsResponse,
  ReviewResponsivenessResponse,
} from './types'

/**
 * Fetch developer statistics
 */
export async function fetchDeveloperStats(
  owner: string,
  repo: string
): Promise<StatsResponse> {
  return api.get<StatsResponse>(`/repos/${owner}/${repo}/stats`)
}

/**
 * Fetch code activity
 */
export async function fetchCodeActivity(
  owner: string,
  repo: string,
  weeks: number = 52
): Promise<CodeActivityResponse> {
  return api.get<CodeActivityResponse>(
    `/repos/${owner}/${repo}/code-activity?weeks=${weeks}`
  )
}

/**
 * Fetch PR lifecycle metrics
 */
export async function fetchLifecycleMetrics(
  owner: string,
  repo: string
): Promise<LifecycleMetricsResponse> {
  return api.get<LifecycleMetricsResponse>(`/repos/${owner}/${repo}/lifecycle-metrics`)
}

/**
 * Fetch review responsiveness
 */
export async function fetchReviewResponsiveness(
  owner: string,
  repo: string
): Promise<ReviewResponsivenessResponse> {
  return api.get<ReviewResponsivenessResponse>(
    `/repos/${owner}/${repo}/review-responsiveness`
  )
}
