import { api } from './client'
import { PipelineRow, PipelineSnapshotResponse } from './types'

export type PipelineFetchResult =
  | { unchanged: true; version: number }
  | ({ unchanged?: false } & PipelineSnapshotResponse)

/**
 * Fetch the pipeline snapshot. Sending the client's current `version` lets the
 * server short-circuit with `{ unchanged: true }` when nothing has changed,
 * which is what makes the 10 s poll cheap. Never touches `gh`.
 */
export async function fetchPipeline(opts: {
  version: number | null
  includeClosed: boolean
}): Promise<PipelineFetchResult> {
  const params = new URLSearchParams()
  params.set('includeClosed', opts.includeClosed ? '1' : '0')
  if (opts.version !== null) params.set('version', String(opts.version))
  return api.get(`/automation/pipeline?${params}`)
}

/**
 * Re-fetch one PR from GitHub, upsert it into synced_prs and return its
 * rebuilt pipeline row. `repo` is `owner/name`.
 */
export async function refreshPipelineRow(
  repo: string,
  prNumber: number
): Promise<{ row: PipelineRow }> {
  return api.post(`/automation/pipeline/${repo}/${prNumber}/refresh`, {})
}
