import { useState, useEffect, useRef, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { Button } from '../common/Button'
import { Alert } from '../common/Alert'
import { Spinner } from '../common/Spinner'
import { getReviewDetail, postVerdict } from '../../api/reviews'
import { getReviewSections, type ReviewSection } from '../../utils/reviewSections'
import type {
  VerdictEvent,
  VerdictInlineComment,
  ReviewDetail,
  ReviewIssueJSON,
} from '../../api/types'

interface VerdictModalProps {
  reviewId: number
  prNumber: number
  repo: string
  onClose: () => void
  onRefresh?: () => void
}

const EVENT_OPTIONS: { value: VerdictEvent; label: string }[] = [
  { value: 'APPROVE', label: 'Approve' },
  { value: 'REQUEST_CHANGES', label: 'Request Changes' },
  { value: 'COMMENT', label: 'Comment' },
]

// Section keys that support inline posting (have file locations)
const INLINE_ELIGIBLE_KEYS = new Set(['critical-issues', 'major-concerns', 'minor-issues'])

/** Editable issue — location is read-only, problem/fix are editable */
interface EditableIssue {
  title: string
  location: { file: string; start_line: number | null; end_line: number | null }
  problem: string
  fix: string
}

const MIN_PANEL_WIDTH = 300
const MIN_PANEL_HEIGHT = 250
const MIN_PANEL_TOP = 60

// Verdict modal default size and constraints
const VERDICT_MIN_WIDTH = 420
const VERDICT_MIN_HEIGHT = 350

export function VerdictModal({ reviewId, prNumber, repo, onClose, onRefresh }: VerdictModalProps) {
  const [event, setEvent] = useState<VerdictEvent>('COMMENT')
  const [customText, setCustomText] = useState('')
  const [sections, setSections] = useState<ReviewSection[]>([])
  const [editedContent, setEditedContent] = useState<Record<string, string>>({})
  const [enabledSections, setEnabledSections] = useState<Set<string>>(new Set())
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set())
  const [inlineSections, setInlineSections] = useState<Set<string>>(new Set())
  const [structuredIssues, setStructuredIssues] = useState<Record<string, EditableIssue[]>>({})
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [reviewDetail, setReviewDetail] = useState<ReviewDetail | null>(null)
  const [showReviewPanel, setShowReviewPanel] = useState(false)

  // Drag state for the review panel
  const [panelPos, setPanelPos] = useState({ x: 40, y: 80 })
  const [panelSize, setPanelSize] = useState({ w: 520, h: 600 })
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null)
  const resizeRef = useRef<{ startX: number; startY: number; origW: number; origH: number } | null>(null)
  const panelNodeRef = useRef<HTMLDivElement>(null)

  // Drag state for the verdict modal itself
  const [verdictPos, setVerdictPos] = useState<{ x: number; y: number } | null>(null)
  const [verdictSize, setVerdictSize] = useState<{ w: number; h: number } | null>(null)
  const verdictDragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null)
  const verdictResizeRef = useRef<{ startX: number; startY: number; origW: number; origH: number } | null>(null)
  const verdictNodeRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadReviewContent()
  }, [reviewId])

  // Close on Escape
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleEscape)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handleEscape)
      document.body.style.overflow = ''
    }
  }, [onClose])

  // Global mousemove/mouseup for drag and resize (both panels)
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      // Review panel drag
      if (dragRef.current) {
        e.preventDefault()
        const dx = e.clientX - dragRef.current.startX
        const dy = e.clientY - dragRef.current.startY
        setPanelPos({
          x: Math.max(0, dragRef.current.origX + dx),
          y: Math.max(MIN_PANEL_TOP, dragRef.current.origY + dy),
        })
      }
      // Review panel resize
      if (resizeRef.current) {
        e.preventDefault()
        const dx = e.clientX - resizeRef.current.startX
        const dy = e.clientY - resizeRef.current.startY
        setPanelSize({
          w: Math.max(MIN_PANEL_WIDTH, resizeRef.current.origW + dx),
          h: Math.max(MIN_PANEL_HEIGHT, resizeRef.current.origH + dy),
        })
      }
      // Verdict modal drag
      if (verdictDragRef.current) {
        e.preventDefault()
        const dx = e.clientX - verdictDragRef.current.startX
        const dy = e.clientY - verdictDragRef.current.startY
        setVerdictPos({
          x: Math.max(0, verdictDragRef.current.origX + dx),
          y: Math.max(0, verdictDragRef.current.origY + dy),
        })
      }
      // Verdict modal resize
      if (verdictResizeRef.current) {
        e.preventDefault()
        const dx = e.clientX - verdictResizeRef.current.startX
        const dy = e.clientY - verdictResizeRef.current.startY
        setVerdictSize({
          w: Math.max(VERDICT_MIN_WIDTH, verdictResizeRef.current.origW + dx),
          h: Math.max(VERDICT_MIN_HEIGHT, verdictResizeRef.current.origH + dy),
        })
      }
    }
    const handleMouseUp = () => {
      dragRef.current = null
      resizeRef.current = null
      verdictDragRef.current = null
      verdictResizeRef.current = null
    }
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [])

  // Review panel drag/resize handlers
  const onPanelDragStart = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button')) return
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origX: panelPos.x,
      origY: panelPos.y,
    }
  }, [panelPos])

  const onPanelResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    resizeRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origW: panelSize.w,
      origH: panelSize.h,
    }
  }, [panelSize])

  // Verdict modal drag/resize handlers
  const onVerdictDragStart = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button')) return
    const node = verdictNodeRef.current
    if (!node) return
    const rect = node.getBoundingClientRect()
    const currentX = verdictPos?.x ?? rect.left
    const currentY = verdictPos?.y ?? rect.top
    verdictDragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origX: currentX,
      origY: currentY,
    }
  }, [verdictPos])

  const onVerdictResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const node = verdictNodeRef.current
    if (!node) return
    const rect = node.getBoundingClientRect()
    const currentW = verdictSize?.w ?? rect.width
    const currentH = verdictSize?.h ?? rect.height
    verdictResizeRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origW: currentW,
      origH: currentH,
    }
  }, [verdictSize])

  const loadReviewContent = async () => {
    try {
      setLoading(true)
      setError(null)
      const review = await getReviewDetail(reviewId)
      setReviewDetail(review)
      const parsed = getReviewSections(review.content, review.content_json)
      setSections(parsed)

      const initialEdits: Record<string, string> = {}
      for (const s of parsed) {
        initialEdits[s.key] = s.content
      }
      setEditedContent(initialEdits)

      // Extract structured issues from content_json for inline-eligible sections
      if (review.content_json?.sections) {
        const issueMap: Record<string, EditableIssue[]> = {}
        for (const jsonSection of review.content_json.sections) {
          const key = jsonSection.type === 'critical' ? 'critical-issues'
            : jsonSection.type === 'major' ? 'major-concerns'
            : 'minor-issues'
          if (jsonSection.issues.length > 0) {
            issueMap[key] = jsonSection.issues.map((issue: ReviewIssueJSON) => ({
              title: issue.title,
              location: { ...issue.location },
              problem: issue.problem,
              fix: issue.fix ?? '',
            }))
          }
        }
        setStructuredIssues(issueMap)
      }
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

  const toggleInline = (key: string) => {
    setInlineSections((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }

  const updateIssueField = (sectionKey: string, issueIdx: number, field: 'problem' | 'fix', value: string) => {
    setStructuredIssues((prev) => {
      const issues = [...(prev[sectionKey] || [])]
      issues[issueIdx] = { ...issues[issueIdx], [field]: value }
      return { ...prev, [sectionKey]: issues }
    })
  }

  /** Build the body text for the verdict (excludes inline sections). */
  const composeBody = (): string => {
    const parts: string[] = []
    if (customText.trim()) {
      parts.push(customText.trim())
    }
    for (const section of sections) {
      if (enabledSections.has(section.key) && !inlineSections.has(section.key)) {
        const content = editedContent[section.key] ?? section.content
        parts.push(`**${section.heading}**\n\n${content}`)
      }
    }
    return parts.join('\n\n---\n\n')
  }

  /** Map section keys to backend section types. */
  const sectionKeyToType = (key: string): string | undefined => {
    if (key === 'critical-issues') return 'critical'
    if (key === 'major-concerns') return 'major'
    if (key === 'minor-issues') return 'minor'
    return undefined
  }

  /** Build inline comment payloads from inline-marked sections. */
  const buildInlineComments = (): VerdictInlineComment[] => {
    const comments: VerdictInlineComment[] = []
    for (const section of sections) {
      if (!enabledSections.has(section.key) || !inlineSections.has(section.key)) continue
      const issues = structuredIssues[section.key]
      if (!issues) continue

      const sectionType = sectionKeyToType(section.key)

      for (const issue of issues) {
        const bodyParts = [`**${issue.title}**`]
        if (issue.problem) bodyParts.push(`\n**Problem:** ${issue.problem}`)
        if (issue.fix) bodyParts.push(`\n**Fix:** ${issue.fix}`)

        comments.push({
          path: issue.location.file,
          body: bodyParts.join('\n'),
          start_line: issue.location.start_line,
          end_line: issue.location.end_line,
          title: issue.title,
          section: sectionType,
        })
      }
    }
    return comments
  }

  const [inlineWarning, setInlineWarning] = useState<string | null>(null)

  const handleSubmit = async () => {
    const body = composeBody()
    const inlineComments = buildInlineComments()

    if (!body && inlineComments.length === 0) {
      setError('Please add custom text, enable a review section, or mark sections for inline posting')
      return
    }

    // Validate inline comments have valid locations
    for (const ic of inlineComments) {
      if (!ic.path || !ic.path.trim()) {
        setError('Cannot post inline: one or more issues is missing a file path')
        return
      }
    }

    try {
      setSubmitting(true)
      setError(null)
      setInlineWarning(null)
      const [owner, repoName] = repo.split('/')
      const result = await postVerdict(owner, repoName, prNumber, {
        event,
        body: body || '',
        inline_comments: inlineComments.length > 0 ? inlineComments : undefined,
        review_id: reviewId,
      })

      // Build detailed success/warning message
      const successParts: string[] = [`${event === 'APPROVE' ? 'Approved' : event === 'REQUEST_CHANGES' ? 'Changes requested' : 'Comment posted'} on PR #${prNumber}`]

      if (result.inline_posted > 0) {
        const total = (result.inline_posted || 0) + (result.inline_errors?.length || 0)
        successParts.push(`${result.inline_posted}/${total} inline comments posted`)
      }

      setSuccess(successParts.join(' — '))

      // Show warning about failed inline comments
      if (result.inline_errors && result.inline_errors.length > 0) {
        const failedDetails: string[] = []
        if (result.section_details) {
          for (const [section, details] of Object.entries(result.section_details)) {
            if (details.failed_titles.length > 0) {
              failedDetails.push(
                `${section}: ${details.failed_titles.join(', ')}`
              )
            }
          }
        }
        const warningMsg = failedDetails.length > 0
          ? `${result.inline_errors.length} inline comment(s) could not be posted (line numbers not in diff):\n${failedDetails.join('\n')}`
          : `${result.inline_errors.length} inline comment(s) could not be posted: ${result.inline_errors.join(', ')}`
        setInlineWarning(warningMsg)
      }

      // Refresh queue to update badges
      onRefresh?.()

      // Auto-close after delay (longer if there are warnings)
      const delay = result.inline_errors?.length ? 4000 : 1500
      setTimeout(onClose, delay)
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

  const hasBodyContent = customText.trim() || [...enabledSections].some((k) => !inlineSections.has(k))
  const hasInlineContent = [...enabledSections].some((k) => inlineSections.has(k) && structuredIssues[k]?.length)
  const hasContent = hasBodyContent || hasInlineContent

  const formatLocation = (loc: EditableIssue['location']) => {
    let s = loc.file
    if (loc.start_line != null && loc.end_line != null && loc.start_line !== loc.end_line) {
      s += `:${loc.start_line}-${loc.end_line}`
    } else if (loc.start_line != null) {
      s += `:${loc.start_line}`
    }
    return s
  }

  const isInlineEligible = (key: string) => INLINE_ELIGIBLE_KEYS.has(key) && !!structuredIssues[key]?.length

  const renderSectionContent = (section: ReviewSection) => {
    const isInline = inlineSections.has(section.key)
    const issues = structuredIssues[section.key]

    // If inline is toggled and we have structured issues, show per-issue editor
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
              <div className="mx-verdict-modal__issue-fields">
                <label className="mx-verdict-modal__issue-field-label">Problem</label>
                <textarea
                  className="mx-verdict-modal__issue-field"
                  value={issue.problem}
                  onChange={(e) => updateIssueField(section.key, idx, 'problem', e.target.value)}
                  disabled={submitting}
                  rows={2}
                />
                <label className="mx-verdict-modal__issue-field-label">Fix</label>
                <textarea
                  className="mx-verdict-modal__issue-field"
                  value={issue.fix}
                  onChange={(e) => updateIssueField(section.key, idx, 'fix', e.target.value)}
                  disabled={submitting}
                  rows={2}
                />
              </div>
            </div>
          ))}
        </div>
      )
    }

    // Default: editable markdown textarea
    return (
      <textarea
        className="mx-verdict-modal__section-preview mx-verdict-modal__section-preview--editable"
        value={editedContent[section.key] ?? section.content}
        onChange={(e) => setEditedContent((prev) => ({
          ...prev,
          [section.key]: e.target.value,
        }))}
        disabled={submitting}
      />
    )
  }

  // Compute inline styles for draggable verdict modal
  const verdictStyle: React.CSSProperties = {
    ...(verdictPos ? { left: verdictPos.x, top: verdictPos.y } : {}),
    ...(verdictSize ? { width: verdictSize.w, height: verdictSize.h } : {}),
  }

  return (
    <>
      <div className="mx-modal-overlay mx-verdict-modal-overlay" onClick={onClose}>
        <div
          ref={verdictNodeRef}
          className={`mx-verdict-modal-draggable${verdictPos ? ' mx-verdict-modal-draggable--positioned' : ''}`}
          style={verdictStyle}
          onClick={(e) => e.stopPropagation()}
        >
          <div
            className="mx-verdict-modal-draggable__header"
            onMouseDown={onVerdictDragStart}
          >
            <h2>Submit Verdict - PR #{prNumber}</h2>
            <button
              className="mx-verdict-modal-draggable__close"
              onClick={onClose}
              aria-label="Close modal"
            >
              ×
            </button>
          </div>
          <div className="mx-verdict-modal-draggable__body">
            {loading ? (
              <div className="mx-verdict-modal__loading">
                <Spinner size="md" />
                <p>Loading review content...</p>
              </div>
            ) : (
              <>
                {error && <Alert variant="error">{error}</Alert>}
                {success && <Alert variant="success">{success}</Alert>}
                {inlineWarning && (
                  <Alert variant="warning">
                    <div style={{ whiteSpace: 'pre-wrap' }}>{inlineWarning}</div>
                  </Alert>
                )}

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
                          <div className="mx-verdict-modal__section-controls">
                            {isInlineEligible(section.key) && enabledSections.has(section.key) && (
                              <label
                                className={`mx-verdict-modal__inline-toggle${
                                  inlineSections.has(section.key) ? ' mx-verdict-modal__inline-toggle--active' : ''
                                }`}
                              >
                                <input
                                  type="checkbox"
                                  checked={inlineSections.has(section.key)}
                                  onChange={() => toggleInline(section.key)}
                                  disabled={submitting}
                                />
                                Inline
                              </label>
                            )}
                            <button
                              className="mx-verdict-modal__expand-btn"
                              onClick={() => toggleExpanded(section.key)}
                            >
                              {expandedSections.has(section.key) ? 'Hide' : 'Edit'}
                            </button>
                          </div>
                        </div>
                        {expandedSections.has(section.key) && renderSectionContent(section)}
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
          </div>
          <div
            className="mx-verdict-modal-draggable__resize-handle"
            onMouseDown={onVerdictResizeStart}
          />
        </div>
      </div>

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
            onMouseDown={onPanelDragStart}
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
            onMouseDown={onPanelResizeStart}
          />
        </div>
      )}
    </>
  )
}
