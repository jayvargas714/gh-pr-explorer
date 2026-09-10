import { api } from './client'
import { AnalyticsDailyResponse } from './types'

export interface AnalyticsDailyParams {
  from: string | null
  to: string
  base: string
}

/**
 * Fetch the precomputed daily analytics rollup
 */
export async function fetchAnalyticsDaily(
  owner: string,
  repo: string,
  p: AnalyticsDailyParams
): Promise<AnalyticsDailyResponse> {
  const params = new URLSearchParams()
  if (p.from !== null) params.set('from', p.from)
  params.set('to', p.to)
  params.set('base', p.base)
  return api.get<AnalyticsDailyResponse>(
    `/repos/${owner}/${repo}/analytics/daily?${params.toString()}`
  )
}
