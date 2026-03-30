import { api } from './client'
import { RepoStatsResponse, LOCResponse } from './types'

export async function fetchRepoStats(
  owner: string,
  repo: string,
  refresh?: boolean
): Promise<RepoStatsResponse> {
  const params = refresh ? '?refresh=true' : ''
  return api.get<RepoStatsResponse>(`/repos/${owner}/${repo}/repo-stats${params}`)
}

export async function fetchLOC(
  owner: string,
  repo: string
): Promise<LOCResponse> {
  return api.post<LOCResponse>(`/repos/${owner}/${repo}/repo-stats/loc`)
}
