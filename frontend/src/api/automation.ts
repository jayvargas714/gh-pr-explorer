import { api } from './client'
import { AutomationConfig, AutomationDispatchRow, ReviewerInfo } from './types'

/** Get the full automation config (stored values merged over the defaults). */
export async function getAutomationConfig(): Promise<{ config: AutomationConfig }> {
  return api.get('/automation/config')
}

/** Save the full automation config. */
export async function saveAutomationConfig(
  config: AutomationConfig
): Promise<{ config: AutomationConfig; message: string }> {
  return api.put('/automation/config', { config })
}

/** List automation pipeline rows, most recently updated first. */
export async function listAutomationDispatches(
  statuses?: string[],
  limit = 200
): Promise<{ dispatches: AutomationDispatchRow[] }> {
  const params = new URLSearchParams()
  if (statuses?.length) params.set('status', statuses.join(','))
  params.set('limit', String(limit))
  return api.get(`/automation/dispatches?${params}`)
}

/** List the reviewer registry (builtins first). */
export async function listReviewers(): Promise<{ reviewers: ReviewerInfo[] }> {
  return api.get('/reviewers')
}

export async function createReviewer(reviewer: {
  key: string
  label: string
  agentName: string
  promptContext?: string | null
}): Promise<{ reviewer: ReviewerInfo }> {
  return api.post('/reviewers', reviewer)
}

export async function updateReviewer(
  key: string,
  updates: { label?: string; agentName?: string; promptContext?: string | null }
): Promise<{ reviewer: ReviewerInfo }> {
  return api.patch(`/reviewers/${encodeURIComponent(key)}`, updates)
}

export async function deleteReviewer(key: string): Promise<{ message: string }> {
  return api.delete(`/reviewers/${encodeURIComponent(key)}`)
}
