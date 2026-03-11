import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import type { Reviewer } from '../../api/types'
import { Badge } from './Badge'

const STATE_LABEL: Record<string, string> = {
  APPROVED: 'Approved',
  CHANGES_REQUESTED: 'Changes Requested',
}

const STATE_COLOR: Record<string, string> = {
  APPROVED: 'var(--mx-color-success)',
  CHANGES_REQUESTED: 'var(--mx-color-error)',
}

interface ReviewersBadgeProps {
  reviewers: Reviewer[]
}

export function ReviewersBadge({ reviewers }: ReviewersBadgeProps) {
  const [showPopup, setShowPopup] = useState(false)
  const [popupPos, setPopupPos] = useState({ x: 0, y: 0 })
  const badgeRef = useRef<HTMLSpanElement>(null)
  const popupRef = useRef<HTMLDivElement>(null)
  const hideTimeout = useRef<number | null>(null)

  if (!reviewers.length) return null

  const approvedCount = reviewers.filter((r) => r.state === 'APPROVED').length

  const handleEnter = () => {
    if (hideTimeout.current) {
      clearTimeout(hideTimeout.current)
      hideTimeout.current = null
    }
    if (badgeRef.current) {
      const rect = badgeRef.current.getBoundingClientRect()
      setPopupPos({ x: rect.left + rect.width / 2, y: rect.bottom + 6 })
    }
    setShowPopup(true)
  }

  const handleLeave = () => {
    hideTimeout.current = window.setTimeout(() => setShowPopup(false), 150)
  }

  const handlePopupEnter = () => {
    if (hideTimeout.current) {
      clearTimeout(hideTimeout.current)
      hideTimeout.current = null
    }
  }

  const handlePopupLeave = () => {
    hideTimeout.current = window.setTimeout(() => setShowPopup(false), 150)
  }

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (hideTimeout.current) clearTimeout(hideTimeout.current)
    }
  }, [])

  // Determine badge variant based on reviewer states
  const hasChangesRequested = reviewers.some((r) => r.state === 'CHANGES_REQUESTED')
  const badgeVariant = hasChangesRequested ? 'warning' : approvedCount > 0 ? 'info' : 'neutral'

  return (
    <>
      <span
        ref={badgeRef}
        onMouseEnter={handleEnter}
        onMouseLeave={handleLeave}
      >
        <Badge variant={badgeVariant}>
          Reviewers ({reviewers.length})
        </Badge>
      </span>
      {showPopup &&
        createPortal(
          <div
            ref={popupRef}
            className="mx-reviewers-popup"
            style={{ left: popupPos.x, top: popupPos.y }}
            onMouseEnter={handlePopupEnter}
            onMouseLeave={handlePopupLeave}
          >
            {reviewers.map((r) => (
              <div key={r.login} className="mx-reviewers-popup__item">
                <img
                  src={r.avatarUrl || `https://github.com/${r.login}.png?size=40`}
                  alt={r.login}
                  className="mx-reviewers-popup__avatar"
                />
                <div className="mx-reviewers-popup__info">
                  <span className="mx-reviewers-popup__name">{r.login}</span>
                  <span
                    className="mx-reviewers-popup__state"
                    style={{ color: STATE_COLOR[r.state] || 'inherit' }}
                  >
                    {STATE_LABEL[r.state] || r.state}
                  </span>
                </div>
              </div>
            ))}
          </div>,
          document.body
        )}
    </>
  )
}
