/**
 * Pure helpers for the PR action controls (draft toggle, merge) and the
 * commits-behind badge. No React — bundle with esbuild to verify.
 */

export type MergeMethod = 'squash' | 'merge' | 'rebase'

export const MERGE_METHODS: { value: MergeMethod; label: string; hint: string }[] = [
  { value: 'squash', label: 'Squash and merge', hint: 'Combine all commits into one' },
  { value: 'merge', label: 'Create a merge commit', hint: 'Keep every commit plus a merge commit' },
  { value: 'rebase', label: 'Rebase and merge', hint: 'Replay each commit onto the base' },
]

export interface MergeEligibilitySubject {
  prState: string | null | undefined
  isDraft: boolean
  reviewDecision: string | null | undefined
}

/** The Merge button shows only for open, non-draft, approved PRs. GitHub
 * still has the final say (branch protection, conflicts, required checks). */
export function canMerge(pr: MergeEligibilitySubject): boolean {
  return pr.prState === 'OPEN' && !pr.isDraft && pr.reviewDecision === 'APPROVED'
}

/** Badge colour for a commits-behind count; thresholds match the PR list. */
export function behindVariant(behindBy: number): 'success' | 'warning' | 'error' {
  if (behindBy <= 0) return 'success'
  if (behindBy <= 10) return 'warning'
  return 'error'
}
