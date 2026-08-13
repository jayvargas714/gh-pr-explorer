import { api } from './client'
import { AutoVerdictConfig, AutoVerdictReviewer } from './types'

/**
 * Get the global auto-verdict criteria (stored values merged over the defaults)
 */
export async function getAutoVerdictConfig(): Promise<{ config: AutoVerdictConfig }> {
  return api.get('/auto-verdict/config')
}

/**
 * Save the global auto-verdict criteria
 */
export async function saveAutoVerdictConfig(
  config: AutoVerdictConfig
): Promise<{ config: AutoVerdictConfig; message: string }> {
  return api.put('/auto-verdict/config', { config })
}

/**
 * Arm or disarm auto verdicts for a queued PR
 */
export async function setCardAutoVerdict(
  prNumber: number,
  repo: string,
  options: { enabled: boolean; reviewerType: AutoVerdictReviewer }
): Promise<{ autoVerdict: { enabled: boolean; reviewerType: AutoVerdictReviewer }; message: string }> {
  return api.put(
    `/merge-queue/${prNumber}/auto-verdict?repo=${encodeURIComponent(repo)}`,
    { enabled: options.enabled, reviewerType: options.reviewerType }
  )
}
