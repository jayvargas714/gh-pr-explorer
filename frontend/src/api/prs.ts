import { api } from './client'
import { PRsResponse, DivergenceResponse, PullRequest } from './types'
import type { MergeInfo, MergeMethod } from '../utils/prActions'

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
 * Fetch a single PR's full details (body, labels, assignees, branches, etc.)
 */
export async function fetchPRDetails(
  owner: string,
  repo: string,
  prNumber: number
): Promise<PullRequest | null> {
  const response = await api.get<PRsResponse>(
    `/repos/${owner}/${repo}/prs?prNumber=${prNumber}`
  )
  return response.prs[0] ?? null
}

/**
 * Live-refresh a single PR (updates the backend's synced store too)
 */
export async function refreshPR(
  owner: string,
  repo: string,
  prNumber: number
): Promise<{ pr: PullRequest }> {
  return api.post<{ pr: PullRequest }>(
    `/repos/${owner}/${repo}/prs/${prNumber}/refresh`,
    {}
  )
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

/**
 * Convert a PR to draft (`draft: true`) or mark it ready for review.
 */
export async function setPRDraft(
  owner: string,
  repo: string,
  prNumber: number,
  draft: boolean
): Promise<{ isDraft: boolean }> {
  return api.post(`/repos/${owner}/${repo}/prs/${prNumber}/draft`, { draft })
}

/**
 * Merge a PR. `headSha` pins the merge to the commit the operator saw, so a
 * push that lands after the dialog opened makes GitHub refuse it.
 */
export async function mergePR(
  owner: string,
  repo: string,
  prNumber: number,
  opts: {
    method: MergeMethod
    deleteBranch: boolean
    headSha?: string | null
    /** Override GitHub's default commit message; omit to keep it. */
    subject?: string
    body?: string
  }
): Promise<{ merged: boolean }> {
  return api.post(`/repos/${owner}/${repo}/prs/${prNumber}/merge`, {
    method: opts.method,
    deleteBranch: opts.deleteBranch,
    ...(opts.headSha ? { headSha: opts.headSha } : {}),
    ...(opts.subject !== undefined ? { subject: opts.subject } : {}),
    ...(opts.body !== undefined ? { body: opts.body } : {}),
  })
}

/**
 * Allowed merge methods and GitHub's pre-filled commit message per method.
 */
export async function fetchMergeInfo(owner: string, repo: string, prNumber: number): Promise<MergeInfo> {
  return api.get(`/repos/${owner}/${repo}/prs/${prNumber}/merge-info`)
}
