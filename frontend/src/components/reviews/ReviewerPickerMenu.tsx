import { useEffect, useRef } from 'react'
import type { ReviewerType } from '../../api/reviews'

interface ReviewerPickerMenuProps {
  onSelect: (reviewer: ReviewerType) => void
  onClose: () => void
}

export function ReviewerPickerMenu({ onSelect, onClose }: ReviewerPickerMenuProps) {
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
      <button
        type="button"
        role="menuitem"
        className="mx-reviewer-picker__option"
        onClick={() => onSelect('default')}
      >
        <span className="mx-reviewer-picker__icon">📋</span>
        <span className="mx-reviewer-picker__label">
          <strong>Default Reviewer</strong>
          <small>elite-code-reviewer</small>
        </span>
      </button>
      <button
        type="button"
        role="menuitem"
        className="mx-reviewer-picker__option"
        onClick={() => onSelect('pb')}
      >
        <span className="mx-reviewer-picker__icon">📝</span>
        <span className="mx-reviewer-picker__label">
          <strong>Product Brief Reviewer</strong>
          <small>product-brief-reviewer</small>
        </span>
      </button>
    </div>
  )
}
