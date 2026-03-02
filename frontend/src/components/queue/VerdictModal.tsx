import { useState, useEffect, useRef, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { Modal } from '../common/Modal'
import { Button } from '../common/Button'
import { Alert } from '../common/Alert'
import { Spinner } from '../common/Spinner'
import { getReviewDetail, postVerdict } from '../../api/reviews'
import { parseReviewSections, type ReviewSection } from '../../utils/reviewSections'
import type { VerdictEvent, ReviewDetail } from '../../api/types'

interface VerdictModalProps {
  reviewId: number
  prNumber: number
  repo: string
  onClose: () => void
}

const EVENT_OPTIONS: { value: VerdictEvent; label: string }[] = [
  { value: 'APPROVE', label: 'Approve' },
  { value: 'REQUEST_CHANGES', label: 'Request Changes' },
  { value: 'COMMENT', label: 'Comment' },
]

const MIN_PANEL_WIDTH = 300
const MIN_PANEL_HEIGHT = 250

export function VerdictModal({ reviewId, prNumber, repo, onClose }: VerdictModalProps) {
  const [event, setEvent] = useState<VerdictEvent>('COMMENT')
  const [customText, setCustomText] = useState('')
  const [sections, setSections] = useState<ReviewSection[]>([])
  const [enabledSections, setEnabledSections] = useState<Set<string>>(new Set())
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [reviewDetail, setReviewDetail] = useState<ReviewDetail | null>(null)
  const [showReviewPanel, setShowReviewPanel] = useState(false)

  // Drag state
  const [panelPos, setPanelPos] = useState({ x: 40, y: 40 })
  const [panelSize, setPanelSize] = useState({ w: 520, h: 600 })
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null)
  const resizeRef = useRef<{ startX: number; startY: number; origW: number; origH: number } | null>(null)
  const panelNodeRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadReviewContent()
  }, [reviewId])

  // Global mousemove/mouseup for drag and resize
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (dragRef.current) {
        e.preventDefault()
        const dx = e.clientX - dragRef.current.startX
        const dy = e.clientY - dragRef.current.startY
        setPanelPos({
          x: Math.max(0, dragRef.current.origX + dx),
          y: Math.max(0, dragRef.current.origY + dy),
        })
      }
      if (resizeRef.current) {
        e.preventDefault()
        const dx = e.clientX - resizeRef.current.startX
        const dy = e.clientY - resizeRef.current.startY
        setPanelSize({
          w: Math.max(MIN_PANEL_WIDTH, resizeRef.current.origW + dx),
          h: Math.max(MIN_PANEL_HEIGHT, resizeRef.current.origH + dy),
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
    // Only drag from the header area, not child buttons
    if ((e.target as HTMLElement).closest('button')) return
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origX: panelPos.x,
      origY: panelPos.y,
    }
  }, [panelPos])

  const onResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    resizeRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origW: panelSize.w,
      origH: panelSize.h,
    }
  }, [panelSize])

  const loadReviewContent = async () => {
    try {
      setLoading(true)
      setError(null)
      const review = await getReviewDetail(reviewId)
      setReviewDetail(review)
      const parsed = parseReviewSections(review.content || '')
      setSections(parsed)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load review content')
    } finally {
      setLoading(false)
    }
  }

  const toggleSection = (key: string) => {
    setEnabledSections((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }

  const toggleExpanded = (key: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }

  const composeBody = (): string => {
    const parts: string[] = []
    if (customText.trim()) {
      parts.push(customText.trim())
    }
    for (const section of sections) {
      if (enabledSections.has(section.key)) {
        parts.push(`**${section.heading}**\n\n${section.content}`)
      }
    }
    return parts.join('\n\n---\n\n')
  }

  const handleSubmit = async () => {
    const body = composeBody()
    if (!body) {
      setError('Please add custom text or enable at least one review section')
      return
    }

    try {
      setSubmitting(true)
      setError(null)
      const [owner, repoName] = repo.split('/')
      const result = await postVerdict(owner, repoName, prNumber, { event, body })
      setSuccess(result.message)
      setTimeout(onClose, 1500)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to post verdict')
    } finally {
      setSubmitting(false)
    }
  }

  const getSubmitVariant = (): 'primary' | 'danger' | 'secondary' => {
    switch (event) {
      case 'APPROVE': return 'primary'
      case 'REQUEST_CHANGES': return 'danger'
      default: return 'secondary'
    }
  }

  const hasContent = customText.trim() || enabledSections.size > 0

  return (
    <>
      <Modal title={`Submit Verdict - PR #${prNumber}`} onClose={onClose} size="lg">
        {loading ? (
          <div className="mx-verdict-modal__loading">
            <Spinner size="md" />
            <p>Loading review content...</p>
          </div>
        ) : (
          <>
            {error && <Alert variant="error">{error}</Alert>}
            {success && <Alert variant="success">{success}</Alert>}

            {reviewDetail && (
              <div className="mx-verdict-modal__review-toggle">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setShowReviewPanel(!showReviewPanel)}
                >
                  {showReviewPanel ? 'Hide Review' : 'View Review'}
                </Button>
                {reviewDetail.score !== null && reviewDetail.score !== undefined && (
                  <span className="mx-verdict-modal__score">
                    Score: {reviewDetail.score}/10
                  </span>
                )}
              </div>
            )}

            <div className="mx-verdict-modal__event-selector">
              <label className="mx-verdict-modal__label">Review Action</label>
              <div className="mx-verdict-modal__event-buttons">
                {EVENT_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    className={`mx-verdict-modal__event-btn mx-verdict-modal__event-btn--${opt.value.toLowerCase().replace('_', '-')}${
                      event === opt.value ? ' mx-verdict-modal__event-btn--active' : ''
                    }`}
                    onClick={() => setEvent(opt.value)}
                    disabled={submitting}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="mx-verdict-modal__custom-text">
              <label className="mx-verdict-modal__label">Custom Text</label>
              <textarea
                className="mx-verdict-modal__textarea"
                placeholder="Add your review comments..."
                value={customText}
                onChange={(e) => setCustomText(e.target.value)}
                rows={4}
                disabled={submitting}
              />
            </div>

            {sections.length > 0 && (
              <div className="mx-verdict-modal__sections">
                <label className="mx-verdict-modal__label">Include Review Sections</label>
                {sections.map((section) => (
                  <div key={section.key} className="mx-verdict-modal__section-toggle">
                    <div className="mx-verdict-modal__section-header">
                      <label className="mx-verdict-modal__checkbox-label">
                        <input
                          type="checkbox"
                          checked={enabledSections.has(section.key)}
                          onChange={() => toggleSection(section.key)}
                          disabled={submitting}
                        />
                        {section.heading}
                      </label>
                      <button
                        className="mx-verdict-modal__expand-btn"
                        onClick={() => toggleExpanded(section.key)}
                      >
                        {expandedSections.has(section.key) ? 'Hide' : 'Preview'}
                      </button>
                    </div>
                    {expandedSections.has(section.key) && (
                      <pre className="mx-verdict-modal__section-preview">
                        {section.content}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            )}

            <div className="mx-verdict-modal__actions">
              <Button variant="ghost" onClick={onClose} disabled={submitting}>
                Cancel
              </Button>
              <Button
                variant={getSubmitVariant()}
                onClick={handleSubmit}
                disabled={submitting || !hasContent}
              >
                {submitting ? 'Submitting...' : `Submit ${EVENT_OPTIONS.find((o) => o.value === event)?.label}`}
              </Button>
            </div>
          </>
        )}
      </Modal>

      {showReviewPanel && reviewDetail && (
        <div
          ref={panelNodeRef}
          className="mx-verdict-review-panel"
          style={{
            left: panelPos.x,
            top: panelPos.y,
            width: panelSize.w,
            height: panelSize.h,
          }}
        >
          <div
            className="mx-verdict-review-panel__header"
            onMouseDown={onDragStart}
          >
            <h3>Code Review - PR #{prNumber}</h3>
            <button
              className="mx-verdict-review-panel__close"
              onClick={() => setShowReviewPanel(false)}
              aria-label="Close review panel"
            >
              ×
            </button>
          </div>
          <div className="mx-verdict-review-panel__content mx-markdown-body">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeHighlight]}
            >
              {reviewDetail.content || 'No content available'}
            </ReactMarkdown>
          </div>
          <div
            className="mx-verdict-review-panel__resize-handle"
            onMouseDown={onResizeStart}
          />
        </div>
      )}
    </>
  )
}
