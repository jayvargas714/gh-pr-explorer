import { api } from './client'
import { PRsResponse, DivergenceResponse } from './types'

/**
 * Fetch PRs with filters
 */
export async function fetchPRs(
  owner: string,
  repo: string,
  filters: Record<string, any>
): Promise<PRsResponse> {
  const params = new URLSearchParams()

  Object.entries(filters).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) {
      if (Array.isArray(value)) {
        if (value.length > 0) {
          params.append(key, value.join(','))
        }
      } else {
        params.append(key, String(value))
      }
    }
  })

  const queryString = params.toString()
  const endpoint = `/repos/${owner}/${repo}/prs${queryString ? `?${queryString}` : ''}`

  return api.get<PRsResponse>(endpoint)
}

/**
 * Fetch branch divergence for multiple PRs
 */
export async function fetchDivergence(
  owner: string,
  repo: string,
  prs: Array<{ number: number; base: string; head: string }>
): Promise<DivergenceResponse> {
  return api.post<DivergenceResponse>(`/repos/${owner}/${repo}/prs/divergence`, {
    prs,
  })
}
