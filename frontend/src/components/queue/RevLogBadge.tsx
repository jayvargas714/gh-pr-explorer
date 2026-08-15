import { useState, useRef } from 'react'
import { createPortal } from 'react-dom'
import { Badge } from '../common/Badge'
import type { RevLogEntry } from '../../api/types'

/**
 * DB timestamps are naive UTC ("YYYY-MM-DD HH:MM:SS[.ffffff]"), so normalize to
 * an explicit UTC instant and let the browser render it in the viewer's local
 * timezone. Without the trailing "Z", `new Date` would parse the string as local
 * time and display the UTC wall-clock numbers, landing hours off.
 */
export function formatLocalDateTime(dbTimestamp: string): string {
  let s = dbTimestamp.trim().replace(' ', 'T')
  if (!/[zZ]|[+-]\d\d:?\d\d$/.test(s)) s += 'Z'
  const d = new Date(s)
  if (isNaN(d.getTime())) return dbTimestamp
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

interface RevLogBadgeProps {
  entries: RevLogEntry[]
  onOpenReview: (id: number) => void
  onOpenAudit: (id: number) => void
}

const AGENT_META: Record<string, { label: string }> = {
  default: { label: 'Code' },
  pb: { label: 'PB' },
  ed: { label: 'ED' },
  pb_ed: { label: 'PB/ED' },
}

const AUTO_EVENT_LABELS: Record<string, string> = {
  APPROVE: '✓ approved',
  REQUEST_CHANGES: '✗ changes requested',
  COMMENT: '💬 comment',
}

const KIND_LABELS: Record<RevLogEntry['kind'], string> = {
  review: 'REVIEW',
  audit: 'AUDIT',
  auto_verdict: 'AUTO',
}

function scoreClass(score: number): string {
  if (score >= 7) return 'mx-revlog-score--good'
  if (score >= 4) return 'mx-revlog-score--ok'
  return 'mx-revlog-score--bad'
}

export function RevLogBadge({ entries, onOpenReview, onOpenAudit }: RevLogBadgeProps) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 })
  const triggerRef = useRef<HTMLSpanElement>(null)
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  if (!entries || entries.length === 0) return null

  const show = () => {
    if (hideTimer.current) clearTimeout(hideTimer.current)
    const rect = triggerRef.current?.getBoundingClientRect()
    if (rect) setPos({ top: rect.bottom + 6, left: rect.left })
    setOpen(true)
  }

  const hide = () => {
    hideTimer.current = setTimeout(() => setOpen(false), 150)
  }

  const renderResult = (e: RevLogEntry) => {
    // Auto verdicts carry an outcome (posted/suppressed/skipped/error) rather
    // than the completed/failed status reviews and audits use.
    if (e.kind === 'auto_verdict') {
      return (
        <span className="mx-revlog-result">
          <span className={`mx-revlog-verdict mx-revlog-verdict--${e.status}`}>
            {e.status === 'posted' ? AUTO_EVENT_LABELS[e.event ?? ''] ?? 'posted' : e.status}
          </span>
        </span>
      )
    }
    if (e.status !== 'completed') {
      return (
        <span className="mx-revlog-status">
          {e.status}
          {e.kind === 'review' && e.autoStarted && (
            <span className="mx-revlog-autostart">🤖 auto</span>
          )}
        </span>
      )
    }
    if (e.kind === 'review') {
      return (
        <span className="mx-revlog-result">
          {e.score !== null && e.score !== undefined ? (
            <span className={`mx-revlog-score ${scoreClass(e.score)}`}>{e.score}/10</span>
          ) : (
            <span className="mx-revlog-score mx-revlog-score--neutral">no score</span>
          )}
          {e.isFollowup && <span className="mx-revlog-followup">follow-up</span>}
          {e.autoStarted && <span className="mx-revlog-autostart">🤖 auto</span>}
        </span>
      )
    }
    return (
      <span className="mx-revlog-result">
        {e.findingCount ?? 0} findings
        <span className={(e.blockingCount ?? 0) > 0 ? 'mx-revlog-blocking' : 'mx-revlog-clean'}>
          {' · '}{e.blockingCount ?? 0} blocking
        </span>
      </span>
    )
  }

  return (
    <span
      ref={triggerRef}
      className="mx-revlog-badge"
      onMouseEnter={show}
      onMouseLeave={hide}
      onClick={(e) => e.stopPropagation()}
    >
      <Badge variant="neutral">rev log ({entries.length})</Badge>
      {open &&
        createPortal(
          <div
            className="mx-revlog-popup"
            style={{ top: pos.top, left: pos.left }}
            onMouseEnter={show}
            onMouseLeave={hide}
          >
            {entries.map((e) => (
              <button
                key={`${e.kind}-${e.id}`}
                type="button"
                className="mx-revlog-row"
                title={e.kind === 'auto_verdict' ? e.reason ?? undefined : undefined}
                onClick={() => {
                  if (e.kind === 'review') onOpenReview(e.id)
                  else if (e.kind === 'audit') onOpenAudit(e.id)
                  // Auto verdicts open the review they were derived from.
                  else if (e.reviewId) onOpenReview(e.reviewId)
                }}
              >
                <span className={`mx-revlog-tag mx-revlog-tag--${e.kind}`}>
                  {KIND_LABELS[e.kind]}
                </span>
                {renderResult(e)}
                {e.reviewerAgent && AGENT_META[e.reviewerAgent] && (
                  <span className={`mx-revlog-agent mx-revlog-agent--${e.reviewerAgent}`}>
                    {AGENT_META[e.reviewerAgent].label}
                  </span>
                )}
                <span className="mx-revlog-when">{formatLocalDateTime(e.timestamp)}</span>
              </button>
            ))}
          </div>,
          document.body
        )}
    </span>
  )
}
