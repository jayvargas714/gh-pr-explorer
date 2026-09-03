import { api } from './client'
import {
  AutoVerdictConfig,
  AutoVerdictCriteriaOverride,
  AutoVerdictMode,
  AutoVerdictReviewer,
} from './types'

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
 * Arm or disarm auto verdicts for a PR. `repo` is `owner/name`; arming is
 * per-PR and no longer requires merge-queue membership.
 */
export async function setCardAutoVerdict(
  prNumber: number,
  repo: string,
  options: { enabled: boolean; reviewerType: AutoVerdictReviewer; mode: AutoVerdictMode }
): Promise<{
  autoVerdict: { enabled: boolean; reviewerType: AutoVerdictReviewer; mode: AutoVerdictMode }
  message: string
}> {
  return api.put(`/prs/${repo}/${prNumber}/auto-verdict`, {
    enabled: options.enabled,
    reviewerType: options.reviewerType,
    mode: options.mode,
  })
}

/**
 * Set (or clear, with null) a PR's auto-verdict criteria override
 */
export async function setCardAutoVerdictCriteria(
  prNumber: number,
  repo: string,
  criteria: AutoVerdictCriteriaOverride | null
): Promise<{ criteriaOverride: AutoVerdictCriteriaOverride | null; message: string }> {
  return api.put(`/prs/${repo}/${prNumber}/auto-verdict/criteria`, { criteria })
}
