/**
 * Pure helpers for the pipeline overlay: stage presentation, row filtering,
 * sorting and the header counts. No React, no store — bundle with esbuild and
 * run against a captured payload to verify.
 */
import type { PipelineRow, PipelineStage } from '../../api/types'
import {
  BadgeFilterKey,
  BadgeFilterMode,
  BadgeSubject,
  subjectMatchesBadges,
  subjectMatchesQuery,
} from '../../utils/badgeFilters'

export interface PipelineFilters {
  query: string
  stages: Set<PipelineStage>
  badgeFilters: Set<BadgeFilterKey>
  badgeFilterMode: BadgeFilterMode
  /** `owner/name`; empty string = any repo. */
  repo: string
  /** Dispatch reviewer key; empty string = any reviewer. */
  reviewerKey: string
  minRounds: number
}

export type PipelineSortColumn =
  | 'pr' | 'stage' | 'rounds' | 'auto' | 'ci' | 'review' | 'issues' | 'updated'

export interface PipelineSort {
  column: PipelineSortColumn
  dir: 'asc' | 'desc'
}

export interface StagePresentation {
  icon: string
  label: string
  /** Short, row-specific qualifier shown after the label (may be empty). */
  reason: string
  /** Default sort rank: things needing the operator first, closed last. */
  priority: number
}

// Attention-first ordering: failed/unidentified need a human, reviewing is
// live, ready/waiting are the pipeline doing its job, reviewed is done.
export const STAGE_ORDER: PipelineStage[] = [
  'failed', 'unidentified', 'reviewing', 'ready', 'waiting',
  'reviewed', 'skipped', 'opted_out', 'closed',
]

export const STAGE_META: Record<PipelineStage, { icon: string; label: string }> = {
  waiting:      { icon: '⏳', label: 'waiting' },
  ready:        { icon: '▷', label: 'ready' },
  reviewing:    { icon: '▶', label: 'reviewing' },
  reviewed:     { icon: '✓', label: 'reviewed' },
  unidentified: { icon: '❓', label: 'unidentified' },
  skipped:      { icon: '⤼', label: 'skipped' },
  opted_out:    { icon: '⏸', label: 'opted out' },
  failed:       { icon: '✗', label: 'failed' },
  closed:       { icon: '●', label: 'closed' },
}

const VERDICT_LABEL: Record<string, string> = {
  APPROVE: 'approved',
  REQUEST_CHANGES: 'changes requested',
  COMMENT: 'comment',
}

const DECISION_LABEL: Record<string, string> = {
  APPROVED: 'approved',
  CHANGES_REQUESTED: 'changes requested',
  REVIEW_REQUIRED: 'review required',
}

/** GitHub URL for a row; synced data may be missing, so fall back to the canonical form. */
export function prUrl(row: PipelineRow): string {
  return row.url ?? `https://github.com/${row.repo}/pull/${row.prNumber}`
}

/**
 * Whether commits landed after the latest review. Server-derived from the
 * synced head SHA vs the latest review's SHA; false whenever either is unknown
 * (never a false positive).
 */
export function hasNewCommits(row: PipelineRow): boolean {
  return row.hasNewCommits === true
}

function reviewedReason(row: PipelineRow): string {
  const parts: string[] = []
  if (row.review?.score != null) parts.push(`${row.review.score}/10`)
  const last = row.autoVerdict?.last
  if (last?.outcome === 'posted' && last.event && VERDICT_LABEL[last.event]) {
    parts.push(VERDICT_LABEL[last.event])
  } else if (row.reviewDecision && DECISION_LABEL[row.reviewDecision]) {
    parts.push(DECISION_LABEL[row.reviewDecision])
  }
  return parts.join(' · ')
}

/** Icon, label, qualifier and sort priority for a row's stage. */
export function stagePresentation(row: PipelineRow): StagePresentation {
  const meta = STAGE_META[row.stage] ?? { icon: '·', label: row.stage }
  const rank = STAGE_ORDER.indexOf(row.stage)
  const priority = rank === -1 ? STAGE_ORDER.length : rank
  const detail = row.dispatch.detail ?? ''
  let reason = ''
  switch (row.stage) {
    case 'waiting':
      // Details read "waiting: CI pending" / "waiting — behind base"; keep the tail.
      reason = detail.replace(/^waiting\b[\s:—–-]*/i, '').trim() || 'dispatch conditions'
      break
    case 'ready':
      reason = detail || 'conditions met'
      break
    case 'reviewing':
      reason = `round ${Math.max(1, row.rounds)}`
      break
    case 'reviewed':
      reason = reviewedReason(row)
      break
    case 'unidentified':
      reason = `rules: ${row.dispatch.matchedRules.join(', ') || 'none'}`
      break
    case 'opted_out':
      reason = 'manual opt-out'
      break
    case 'closed':
      reason = (row.prState ?? 'closed').toLowerCase()
      break
    case 'skipped':
    case 'failed':
      reason = detail
      break
  }
  return { icon: meta.icon, label: meta.label, reason, priority }
}

/** Adapt a pipeline row to the badge-predicate shape shared with board cards. */
export function rowToBadgeSubject(row: PipelineRow): BadgeSubject {
  return {
    number: row.prNumber,
    title: row.title,
    author: row.author,
    repo: row.repo,
    prState: row.prState,
    isDraft: row.isDraft,
    reviewDecision: row.reviewDecision,
    ciStatus: row.ciStatus,
    hasReview: row.review !== null,
    reviewScore: row.review?.score ?? null,
    hasNewCommits: hasNewCommits(row),
    isFollowup: row.review?.isFollowup ?? false,
    currentReviewers: row.currentReviewers,
    autoVerdict: row.autoVerdict,
    // The dispatch status is authoritative for the ❓ Unidentified chip even
    // when the enrichment-shaped `automation` block is missing.
    automation: row.automation ?? { status: row.dispatch.status },
  }
}

/** Combined visibility check; every inactive filter passes. */
export function rowPassesFilters(row: PipelineRow, f: PipelineFilters): boolean {
  if (f.stages.size > 0 && !f.stages.has(row.stage)) return false
  if (f.repo && row.repo !== f.repo) return false
  if (f.reviewerKey && row.dispatch.reviewerKey !== f.reviewerKey) return false
  if (row.rounds < f.minRounds) return false
  const subject = rowToBadgeSubject(row)
  if (f.query.trim().length > 0 && !subjectMatchesQuery(subject, f.query)) return false
  return subjectMatchesBadges(subject, f.badgeFilters, f.badgeFilterMode)
}

const CI_RANK: Record<string, number> = { success: 0, pending: 1, failure: 2 }
const DECISION_RANK: Record<string, number> = {
  APPROVED: 0,
  REVIEW_REQUIRED: 1,
  CHANGES_REQUESTED: 2,
}

function updatedMs(row: PipelineRow): number {
  const t = row.prUpdatedAt ? Date.parse(row.prUpdatedAt) : NaN
  return Number.isNaN(t) ? 0 : t
}

function issuesFound(row: PipelineRow): number {
  const r = row.review
  if (!r) return -1
  return (r.critical.found ?? 0) + (r.major.found ?? 0) + (r.minor.found ?? 0)
}

function columnCompare(column: PipelineSortColumn, a: PipelineRow, b: PipelineRow): number {
  switch (column) {
    case 'pr':
      return a.repo.localeCompare(b.repo) || a.prNumber - b.prNumber
    case 'stage':
      return stagePresentation(a).priority - stagePresentation(b).priority
    case 'rounds':
      return a.rounds - b.rounds
    case 'auto':
      return Number(!!b.autoVerdict?.enabled) - Number(!!a.autoVerdict?.enabled)
    case 'ci':
      return (CI_RANK[a.ciStatus ?? ''] ?? 3) - (CI_RANK[b.ciStatus ?? ''] ?? 3)
    case 'review':
      return (DECISION_RANK[a.reviewDecision ?? ''] ?? 3) - (DECISION_RANK[b.reviewDecision ?? ''] ?? 3)
    case 'issues':
      return issuesFound(a) - issuesFound(b)
    case 'updated':
      return updatedMs(a) - updatedMs(b)
  }
}

/**
 * Comparator for the given sort. Ties always fall back to most-recently
 * updated first, then key, so the order is stable across polls. The default
 * view is `{ column: 'stage', dir: 'asc' }` → stage priority asc, updated desc.
 */
export function compareRows(sort: PipelineSort): (a: PipelineRow, b: PipelineRow) => number {
  const sign = sort.dir === 'asc' ? 1 : -1
  return (a, b) => {
    const primary = columnCompare(sort.column, a, b) * sign
    if (primary !== 0) return primary
    const byUpdated = updatedMs(b) - updatedMs(a)
    if (byUpdated !== 0) return byUpdated
    return a.key.localeCompare(b.key)
  }
}

export interface PipelineSummary {
  total: number
  /** Pre-dispatch rows: `waiting` + `ready`. */
  waiting: number
  reviewing: number
  reviewed: number
  /** Needs a human: unidentified + failed + changes-requested with new commits. */
  attention: number
}

export function summarize(rows: PipelineRow[]): PipelineSummary {
  const out: PipelineSummary = { total: rows.length, waiting: 0, reviewing: 0, reviewed: 0, attention: 0 }
  for (const row of rows) {
    switch (row.stage) {
      case 'waiting':
      case 'ready':
        out.waiting++
        break
      case 'reviewing':
        out.reviewing++
        break
      case 'reviewed':
        out.reviewed++
        break
      case 'unidentified':
      case 'failed':
        out.attention++
        break
    }
    if (
      row.stage !== 'unidentified' &&
      row.stage !== 'failed' &&
      row.reviewDecision === 'CHANGES_REQUESTED' &&
      hasNewCommits(row)
    ) {
      out.attention++
    }
  }
  return out
}
