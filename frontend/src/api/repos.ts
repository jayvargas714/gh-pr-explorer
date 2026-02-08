import { api } from './client'
import {
  AccountsResponse,
  ReposResponse,
  ContributorsResponse,
  LabelsResponse,
  BranchesResponse,
  MilestonesResponse,
  TeamsResponse,
} from './types'

/**
 * Fetch user accounts and organizations
 */
export async function fetchAccounts(): Promise<AccountsResponse> {
  return api.get<AccountsResponse>('/orgs')
}

/**
 * Fetch repositories for an owner
 */
export async function fetchRepos(
  owner: string,
  limit: number = 200
): Promise<ReposResponse> {
  return api.get<ReposResponse>(`/repos?owner=${owner}&limit=${limit}`)
}

/**
 * Fetch repository contributors
 */
export async function fetchContributors(
  owner: string,
  repo: string
): Promise<ContributorsResponse> {
  return api.get<ContributorsResponse>(`/repos/${owner}/${repo}/contributors`)
}

/**
 * Fetch repository labels
 */
export async function fetchLabels(
  owner: string,
  repo: string
): Promise<LabelsResponse> {
  return api.get<LabelsResponse>(`/repos/${owner}/${repo}/labels`)
}

/**
 * Fetch repository branches
 */
export async function fetchBranches(
  owner: string,
  repo: string
): Promise<BranchesResponse> {
  return api.get<BranchesResponse>(`/repos/${owner}/${repo}/branches`)
}

/**
 * Fetch repository milestones
 */
export async function fetchMilestones(
  owner: string,
  repo: string
): Promise<MilestonesResponse> {
  return api.get<MilestonesResponse>(`/repos/${owner}/${repo}/milestones`)
}

/**
 * Fetch repository teams
 */
export async function fetchTeams(
  owner: string,
  repo: string
): Promise<TeamsResponse> {
  return api.get<TeamsResponse>(`/repos/${owner}/${repo}/teams`)
}

/**
 * Fetch all repository metadata in parallel
 */
export async function fetchRepoMetadata(owner: string, repo: string) {
  const [contributors, labels, branches, milestones, teams] = await Promise.allSettled([
    fetchContributors(owner, repo),
    fetchLabels(owner, repo),
    fetchBranches(owner, repo),
    fetchMilestones(owner, repo),
    fetchTeams(owner, repo),
  ])

  return {
    contributors:
      contributors.status === 'fulfilled' ? contributors.value.contributors : [],
    labels: labels.status === 'fulfilled' ? labels.value.labels : [],
    branches: branches.status === 'fulfilled' ? branches.value.branches : [],
    milestones: milestones.status === 'fulfilled' ? milestones.value.milestones : [],
    teams: teams.status === 'fulfilled' ? teams.value.teams : [],
  }
}
