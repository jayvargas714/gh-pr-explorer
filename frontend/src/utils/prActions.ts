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

export interface MergeMessage {
  subject: string
  body: string
}

/** GET /prs/<n>/merge-info: what the repo allows, and GitHub's pre-filled
 * commit message per method (rebase replays commits, so it has none). */
export interface MergeInfo {
  methods: {
    squash: { allowed: boolean } & MergeMessage
    merge: { allowed: boolean } & MergeMessage
    rebase: { allowed: boolean }
  }
}

/** Squash when the repo allows it, else the first allowed method. Without
 * info (still loading or the fetch failed) assume squash. */
export function defaultMergeMethod(info: MergeInfo | null): MergeMethod {
  if (!info) return 'squash'
  return MERGE_METHODS.find((m) => info.methods[m.value].allowed)?.value ?? 'squash'
}

/**
 * The subject/body to send with a merge: only what the operator changed from
 * GitHub's default, so an untouched message lets GitHub apply its own exactly.
 * Without defaults (fetch failed), anything typed is sent; a blank subject is
 * never sent (GitHub requires one).
 */
export function messageOverrides(
  method: MergeMethod,
  draft: MergeMessage,
  defaults: MergeMessage | null
): Partial<MergeMessage> {
  if (method === 'rebase') return {}
  const out: Partial<MergeMessage> = {}
  const subjectChanged = defaults ? draft.subject !== defaults.subject : draft.subject !== ''
  if (subjectChanged && draft.subject.trim() !== '') out.subject = draft.subject
  const bodyChanged = defaults ? draft.body !== defaults.body : draft.body !== ''
  if (bodyChanged) out.body = draft.body
  return out
}
