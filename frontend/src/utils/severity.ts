import type { ReviewSeverity } from '../api/types'

/** The two review severity tiers, in display order. Mirrors `SEVERITIES` in
 * backend/services/review_schema.py: blocking findings must be fixed before
 * the PR can merge; everything else worth reporting is non-blocking. */
export const SEVERITIES: readonly ReviewSeverity[] = ['blocking', 'non_blocking']

export const SEVERITY_LABELS: Record<ReviewSeverity, string> = {
  blocking: 'Blocking',
  non_blocking: 'Non-Blocking',
}

/** Section display names (mirrors `DEFAULT_SECTION_NAMES` on the backend). */
export const SEVERITY_SECTION_HEADINGS: Record<ReviewSeverity, string> = {
  blocking: 'Blocking Issues',
  non_blocking: 'Non-Blocking Issues',
}

/** Frontend section keys per tier (the set-aside sections are keyed by type). */
export const SEVERITY_SECTION_KEYS: Record<ReviewSeverity, string> = {
  blocking: 'blocking-issues',
  non_blocking: 'non-blocking-issues',
}

/** Short cell labels for dense tables such as the pipeline Issues column. */
export const SEVERITY_SHORT: Record<ReviewSeverity, string> = {
  blocking: 'B',
  non_blocking: 'nb',
}

export const SEVERITY_EMOJI: Record<ReviewSeverity, string> = {
  blocking: '🔴',
  non_blocking: '🟢',
}

/** Section keys whose issues carry file locations and may be posted inline.
 * Disputed / Deferred set-asides are deliberately absent. */
export const INLINE_ELIGIBLE_SECTION_KEYS: ReadonlySet<string> = new Set(
  SEVERITIES.map((sev) => SEVERITY_SECTION_KEYS[sev])
)

export function severityFromSectionKey(key: string): ReviewSeverity | undefined {
  return SEVERITIES.find((sev) => SEVERITY_SECTION_KEYS[sev] === key)
}

/** Human label for a severity value; `fallback` when the value is unknown. */
export function severityLabel(value: string | undefined | null, fallback = '—'): string {
  if (!value) return fallback
  return SEVERITY_LABELS[value as ReviewSeverity] ?? fallback
}

export function severityRank(value: string | undefined | null): number {
  const idx = SEVERITIES.indexOf(value as ReviewSeverity)
  return idx === -1 ? SEVERITIES.length : idx
}

/** A threshold for display: `null` means no limit. */
export function formatLimit(limit: number | null | undefined): string {
  return limit == null ? 'unlimited' : String(limit)
}
