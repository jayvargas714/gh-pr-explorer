/**
 * Badge-filter vocabulary and predicates shared by the swimlane board and the
 * pipeline overlay. Both surfaces render the same badges, so a chip must match
 * exactly the rows/cards whose badge is rendered — keeping the predicates here
 * means there is one definition of "CI failed" or "Score ≥ 7".
 *
 * Predicates operate on a `BadgeSubject`: the minimal structural shape both a
 * `MergeQueueItem` (directly) and a `PipelineRow` (via an adapter) satisfy.
 */

// Badge filter keys grouped by visual dimension. Within a dimension, multiple
// picks are OR'd (a single PR can't be both Open and Merged); across
// dimensions, the combinator is controlled by the filter mode.
export type BadgeFilterKey =
  | 'state:open' | 'state:closed' | 'state:merged'
  | 'draft'
  | 'review:approved' | 'review:changes_requested' | 'review:review_required'
  | 'ci:success' | 'ci:failure' | 'ci:pending'
  | 'has_review' | 'score:good' | 'score:ok' | 'score:bad'
  | 'new_commits' | 'reviewers_requested' | 'followup'
  | 'auto:armed' | 'auto:posted' | 'auto:needs_approval' | 'auto:unidentified'

export type BadgeDimension =
  | 'state' | 'draft' | 'review' | 'ci' | 'review_score'
  | 'new_commits' | 'reviewers' | 'followup' | 'auto_verdict'

export const BADGE_DIMENSION: Record<BadgeFilterKey, BadgeDimension> = {
  'state:open': 'state',
  'state:closed': 'state',
  'state:merged': 'state',
  draft: 'draft',
  'review:approved': 'review',
  'review:changes_requested': 'review',
  'review:review_required': 'review',
  'ci:success': 'ci',
  'ci:failure': 'ci',
  'ci:pending': 'ci',
  has_review: 'review_score',
  'score:good': 'review_score',
  'score:ok': 'review_score',
  'score:bad': 'review_score',
  new_commits: 'new_commits',
  reviewers_requested: 'reviewers',
  followup: 'followup',
  'auto:armed': 'auto_verdict',
  'auto:posted': 'auto_verdict',
  'auto:needs_approval': 'auto_verdict',
  'auto:unidentified': 'auto_verdict',
}

export type BadgeFilterMode = 'OR' | 'AND'

/** The fields the badge predicates read. Field names mirror MergeQueueItem. */
export interface BadgeSubject {
  number: number
  title: string | null
  author: string | null
  repo: string
  prState: string | null
  isDraft: boolean
  reviewDecision: string | null
  ciStatus: string | null
  hasReview: boolean
  reviewScore: number | null
  hasNewCommits: boolean
  isFollowup: boolean
  currentReviewers?: { login: string }[] | null
  autoVerdict?: { enabled: boolean; last: { outcome: string } | null } | null
  automation?: { status: string } | null
}

/**
 * Match a subject against the search query. Matches:
 *  - exact PR number (when query is all digits)
 *  - any substring of PR number, title, author, repo (case-insensitive)
 * Empty / whitespace-only query → always false (caller decides what to do).
 */
export function subjectMatchesQuery(subject: BadgeSubject, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return false
  if (/^\d+$/.test(q) && String(subject.number) === q) return true
  const haystack = [
    String(subject.number),
    subject.title || '',
    subject.author || '',
    subject.repo || '',
  ]
    .join(' ')
    .toLowerCase()
  return haystack.includes(q)
}

// Per-key predicate. Field names mirror getStateBadge/getReviewStatusBadge/etc.
// in QueueItem so a filter matches exactly the cards whose badge is rendered.
export function subjectMatchesBadge(s: BadgeSubject, key: BadgeFilterKey): boolean {
  switch (key) {
    case 'state:open':   return s.prState === 'OPEN'
    case 'state:closed': return s.prState === 'CLOSED'
    case 'state:merged': return s.prState === 'MERGED'
    case 'draft':        return !!s.isDraft
    case 'review:approved':          return s.reviewDecision === 'APPROVED'
    case 'review:changes_requested': return s.reviewDecision === 'CHANGES_REQUESTED'
    case 'review:review_required':   return s.reviewDecision === 'REVIEW_REQUIRED'
    case 'ci:success': return s.ciStatus === 'success'
    case 'ci:failure': return s.ciStatus === 'failure'
    case 'ci:pending': return s.ciStatus === 'pending'
    case 'has_review': return !!s.hasReview
    case 'score:good': return !!s.hasReview && s.reviewScore != null && s.reviewScore >= 7
    case 'score:ok':   return !!s.hasReview && s.reviewScore != null && s.reviewScore >= 4 && s.reviewScore <= 6
    case 'score:bad':  return !!s.hasReview && s.reviewScore != null && s.reviewScore < 4
    case 'new_commits':         return !!s.hasNewCommits
    case 'reviewers_requested': return (s.currentReviewers?.length ?? 0) > 0
    case 'followup':            return !!s.isFollowup
    case 'auto:armed':          return !!s.autoVerdict?.enabled
    case 'auto:posted':         return s.autoVerdict?.last?.outcome === 'posted'
    case 'auto:needs_approval': return s.autoVerdict?.last?.outcome === 'suppressed'
    case 'auto:unidentified':   return s.automation?.status === 'unidentified'
  }
}

/**
 * Visibility check for the badge filter. Returns true when no filters are
 * active. With multiple filters: within a dimension picks are OR'd; across
 * dimensions the combinator is `mode`.
 */
export function subjectMatchesBadges(
  subject: BadgeSubject,
  filters: Set<BadgeFilterKey>,
  mode: BadgeFilterMode,
): boolean {
  if (filters.size === 0) return true
  if (mode === 'OR') {
    for (const k of filters) if (subjectMatchesBadge(subject, k)) return true
    return false
  }
  const byDim = new Map<BadgeDimension, BadgeFilterKey[]>()
  for (const k of filters) {
    const dim = BADGE_DIMENSION[k]
    const arr = byDim.get(dim)
    if (arr) arr.push(k)
    else byDim.set(dim, [k])
  }
  for (const keys of byDim.values()) {
    if (!keys.some((k) => subjectMatchesBadge(subject, k))) return false
  }
  return true
}
