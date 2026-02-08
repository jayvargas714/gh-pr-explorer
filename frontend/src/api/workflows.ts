import { api } from './client'
import { WorkflowRunsResponse } from './types'

/**
 * Fetch workflow runs with filters
 */
export async function fetchWorkflowRuns(
  owner: string,
  repo: string,
  filters: {
    limit?: number
    workflow_id?: number
    branch?: string
    event?: string
    status?: string
    conclusion?: string
    refresh?: boolean
  } = {}
): Promise<WorkflowRunsResponse> {
  const params = new URLSearchParams()

  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      params.append(key, String(value))
    }
  })

  const queryString = params.toString()
  return api.get<WorkflowRunsResponse>(
    `/repos/${owner}/${repo}/workflow-runs${queryString ? `?${queryString}` : ''}`
  )
}
