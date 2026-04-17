import { api } from './client'
import type { TimelineResponse } from './types'

interface FetchTimelineOptions {
  refresh?: boolean
}

/**
 * Fetch the normalized timeline for a single PR.
 */
export async function fetchTimeline(
  owner: string,
  repo: string,
  prNumber: number,
  opts: FetchTimelineOptions = {}
): Promise<TimelineResponse> {
  const params = new URLSearchParams()
  if (opts.refresh) params.set('refresh', 'true')
  const qs = params.toString() ? `?${params.toString()}` : ''
  return api.get<TimelineResponse>(
    `/repos/${owner}/${repo}/prs/${prNumber}/timeline${qs}`
  )
}
