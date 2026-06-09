import { useState, useRef } from 'react'
import { createPortal } from 'react-dom'
import { Badge } from '../common/Badge'
import { formatFullDateTime } from '../../utils/formatters'
import type { RevLogEntry } from '../../api/types'

interface RevLogBadgeProps {
  entries: RevLogEntry[]
  onOpenReview: (id: number) => void
  onOpenAudit: (id: number) => void
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
    if (e.status !== 'completed') {
      return <span className="mx-revlog-status">{e.status}</span>
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
                onClick={() => (e.kind === 'review' ? onOpenReview(e.id) : onOpenAudit(e.id))}
              >
                <span className={`mx-revlog-tag mx-revlog-tag--${e.kind}`}>
                  {e.kind === 'review' ? 'REVIEW' : 'AUDIT'}
                </span>
                {renderResult(e)}
                <span className="mx-revlog-when">{formatFullDateTime(e.timestamp)}</span>
              </button>
            ))}
          </div>,
          document.body
        )}
    </span>
  )
}
