import { useEffect, useRef } from 'react'
import type { ReviewerType } from '../../api/reviews'
import { useAutomationStore } from '../../stores/useAutomationStore'

interface ReviewerPickerMenuProps {
  onSelect: (reviewer: ReviewerType) => void
  onClose: () => void
}

// Icons for the builtin reviewers; custom registry entries get a generic one.
const REVIEWER_ICONS: Record<string, string> = {
  default: '📋',
  pb: '📝',
  ed: '📐',
}

export function ReviewerPickerMenu({ onSelect, onClose }: ReviewerPickerMenuProps) {
  const reviewers = useAutomationStore((s) => s.reviewers)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose()
      }
    }
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [onClose])

  return (
    <div
      ref={ref}
      className="mx-reviewer-picker"
      role="menu"
      aria-label="Choose reviewer"
    >
      {reviewers.map((reviewer) => (
        <button
          key={reviewer.key}
          type="button"
          role="menuitem"
          className="mx-reviewer-picker__option"
          onClick={() => onSelect(reviewer.key)}
        >
          <span className="mx-reviewer-picker__icon">
            {REVIEWER_ICONS[reviewer.key] ?? '🧩'}
          </span>
          <span className="mx-reviewer-picker__label">
            <strong>{reviewer.label}</strong>
            <small>{reviewer.agentName}</small>
          </span>
        </button>
      ))}
    </div>
  )
}
