import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReviewSection } from '../../utils/reviewSections'

export interface EditableIssue {
  title: string
  location: { file: string; start_line: number | null; end_line: number | null }
  principle: string
  problem: string
  fix: string
}

interface SectionEditModalProps {
  section: ReviewSection
  editedContent: string
  isInline: boolean
  issues: EditableIssue[] | undefined
  submitting: boolean
  onContentChange: (newContent: string) => void
  onIssueFieldChange: (issueIdx: number, field: 'problem' | 'fix', value: string) => void
  onClose: () => void
}

const MIN_W = 380
const MIN_H = 280

const formatLocation = (loc: EditableIssue['location']) => {
  let s = loc.file
  if (loc.start_line != null && loc.end_line != null && loc.start_line !== loc.end_line) {
    s += `:${loc.start_line}-${loc.end_line}`
  } else if (loc.start_line != null) {
    s += `:${loc.start_line}`
  }
  return s
}

export function SectionEditModal({
  section,
  editedContent,
  isInline,
  issues,
  submitting,
  onContentChange,
  onIssueFieldChange,
  onClose,
}: SectionEditModalProps) {
  const [pos, setPos] = useState({ x: 160, y: 110 })
  const [size, setSize] = useState({ w: 620, h: 540 })
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null)
  const resizeRef = useRef<{ startX: number; startY: number; origW: number; origH: number } | null>(null)

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [onClose])

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (dragRef.current) {
        e.preventDefault()
        const dx = e.clientX - dragRef.current.startX
        const dy = e.clientY - dragRef.current.startY
        setPos({
          x: Math.max(0, dragRef.current.origX + dx),
          y: Math.max(60, dragRef.current.origY + dy),
        })
      }
      if (resizeRef.current) {
        e.preventDefault()
        const dx = e.clientX - resizeRef.current.startX
        const dy = e.clientY - resizeRef.current.startY
        setSize({
          w: Math.max(MIN_W, resizeRef.current.origW + dx),
          h: Math.max(MIN_H, resizeRef.current.origH + dy),
        })
      }
    }
    const handleMouseUp = () => {
      dragRef.current = null
      resizeRef.current = null
    }
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [])

  const onDragStart = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button')) return
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origX: pos.x,
      origY: pos.y,
    }
  }, [pos])

  const onResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    resizeRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origW: size.w,
      origH: size.h,
    }
  }, [size])

  const renderBody = () => {
    if (isInline && issues?.length) {
      return (
        <div className="mx-verdict-modal__issue-list">
          {issues.map((issue, idx) => (
            <div key={idx} className="mx-verdict-modal__issue-item">
              <div className="mx-verdict-modal__issue-header">
                <span className="mx-verdict-modal__issue-number">{idx + 1}.</span>
                <span className="mx-verdict-modal__issue-title">{issue.title}</span>
              </div>
              <code className="mx-verdict-modal__issue-location">
                {formatLocation(issue.location)}
              </code>
              {issue.principle && (
                <div className="mx-verdict-modal__issue-principle">
                  {issue.principle}
                </div>
              )}
              <div className="mx-verdict-modal__issue-fields">
                <label className="mx-verdict-modal__issue-field-label">Problem</label>
                <textarea
                  className="mx-verdict-modal__issue-field"
                  value={issue.problem}
                  onChange={(e) => onIssueFieldChange(idx, 'problem', e.target.value)}
                  disabled={submitting}
                  rows={3}
                />
                <label className="mx-verdict-modal__issue-field-label">Fix</label>
                <textarea
                  className="mx-verdict-modal__issue-field"
                  value={issue.fix}
                  onChange={(e) => onIssueFieldChange(idx, 'fix', e.target.value)}
                  disabled={submitting}
                  rows={3}
                />
              </div>
            </div>
          ))}
        </div>
      )
    }

    return (
      <textarea
        className="mx-section-edit-modal__textarea"
        value={editedContent}
        onChange={(e) => onContentChange(e.target.value)}
        disabled={submitting}
        autoFocus
      />
    )
  }

  return (
    <div
      className="mx-section-edit-modal"
      style={{ left: pos.x, top: pos.y, width: size.w, height: size.h }}
    >
      <div className="mx-section-edit-modal__header" onMouseDown={onDragStart}>
        <h3>
          Edit: {section.heading}
          {isInline && (
            <span className="mx-section-edit-modal__inline-badge">inline</span>
          )}
        </h3>
        <button
          className="mx-section-edit-modal__close"
          onClick={onClose}
          aria-label="Close section editor"
        >
          ×
        </button>
      </div>
      <div className="mx-section-edit-modal__content">
        {renderBody()}
      </div>
      <div
        className="mx-section-edit-modal__resize-handle"
        onMouseDown={onResizeStart}
      />
    </div>
  )
}
