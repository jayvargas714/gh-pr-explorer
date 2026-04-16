import { useState, useEffect, useRef, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import 'highlight.js/styles/github-dark.css'
import { useReviewStore } from '../../stores/useReviewStore'
import { fetchReviewById } from '../../api/reviews'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'
import { formatRelativeTime } from '../../utils/formatters'

const MIN_WIDTH = 400
const MIN_HEIGHT = 300

export function ReviewViewer() {
  const { showReviewViewer, reviewViewerContent, openReviewViewer, closeReviewViewer } =
    useReviewStore()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copySuccess, setCopySuccess] = useState(false)

  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null)
  const resizeRef = useRef<{ startX: number; startY: number; origW: number; origH: number } | null>(null)
  const nodeRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (showReviewViewer && reviewViewerContent?.id) {
      loadReview(reviewViewerContent.id)
    }
  }, [showReviewViewer, reviewViewerContent?.id])

  // Reset position/size when opening
  useEffect(() => {
    if (showReviewViewer) {
      setPos(null)
      setSize(null)
    }
  }, [showReviewViewer])

  // Close on Escape
  useEffect(() => {
    if (!showReviewViewer) return
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleClose()
    }
    document.addEventListener('keydown', handleEscape)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handleEscape)
      document.body.style.overflow = ''
    }
  }, [showReviewViewer])

  // Global mousemove/mouseup for drag and resize
  useEffect(() => {
    if (!showReviewViewer) return
    const handleMouseMove = (e: MouseEvent) => {
      if (dragRef.current) {
        e.preventDefault()
        const dx = e.clientX - dragRef.current.startX
        const dy = e.clientY - dragRef.current.startY
        setPos({
          x: Math.max(0, dragRef.current.origX + dx),
          y: Math.max(0, dragRef.current.origY + dy),
        })
      }
      if (resizeRef.current) {
        e.preventDefault()
        const dx = e.clientX - resizeRef.current.startX
        const dy = e.clientY - resizeRef.current.startY
        setSize({
          w: Math.max(MIN_WIDTH, resizeRef.current.origW + dx),
          h: Math.max(MIN_HEIGHT, resizeRef.current.origH + dy),
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
  }, [showReviewViewer])

  const onDragStart = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button')) return
    const node = nodeRef.current
    if (!node) return
    const rect = node.getBoundingClientRect()
    if (!size) {
      setSize({ w: rect.width, h: rect.height })
    }
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origX: pos?.x ?? rect.left,
      origY: pos?.y ?? rect.top,
    }
  }, [pos, size])

  const onResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const node = nodeRef.current
    if (!node) return
    const rect = node.getBoundingClientRect()
    if (!pos) {
      setPos({ x: rect.left, y: rect.top })
    }
    if (!size) {
      setSize({ w: rect.width, h: rect.height })
    }
    resizeRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origW: size?.w ?? rect.width,
      origH: size?.h ?? rect.height,
    }
  }, [pos, size])

  const loadReview = async (reviewId: number) => {
    try {
      setLoading(true)
      setError(null)
      const review = await fetchReviewById(reviewId)
      openReviewViewer(review)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load review')
    } finally {
      setLoading(false)
    }
  }

  const handleClose = () => {
    closeReviewViewer()
    setCopySuccess(false)
  }

  const handleCopy = async () => {
    if (!reviewViewerContent?.content) return
    try {
      await navigator.clipboard.writeText(reviewViewerContent.content)
      setCopySuccess(true)
      setTimeout(() => setCopySuccess(false), 2000)
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }

  if (!showReviewViewer) return null

  const modalStyle: React.CSSProperties = {
    ...(pos ? { left: pos.x, top: pos.y } : {}),
    ...(size ? { width: size.w, height: size.h } : {}),
  }

  return (
    <div className="mx-modal-overlay" onClick={handleClose}>
      <div
        ref={nodeRef}
        className={`mx-draggable-modal mx-draggable-modal--xl${pos ? ' mx-draggable-modal--positioned' : ''}`}
        style={modalStyle}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mx-draggable-modal__header" onMouseDown={onDragStart}>
          <h2>Code Review - PR #{reviewViewerContent?.pr_number || reviewViewerContent?.prNumber || ''}</h2>
          <button
            className="mx-draggable-modal__close"
            onClick={handleClose}
            aria-label="Close modal"
          >
            ×
          </button>
        </div>
        <div className="mx-draggable-modal__body">
          {loading ? (
            <div className="mx-review-viewer__loading">
              <Spinner size="lg" />
              <p>Loading review...</p>
            </div>
          ) : error ? (
            <Alert variant="error">{error}</Alert>
          ) : reviewViewerContent ? (
            <>
              <div className="mx-review-viewer__header">
                <div className="mx-review-viewer__meta">
                  <a
                    href={reviewViewerContent.pr_url || reviewViewerContent.prUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mx-review-viewer__pr-link"
                  >
                    {reviewViewerContent.pr_title || reviewViewerContent.prTitle}
                  </a>
                  <span className="mx-review-viewer__time">
                    Reviewed {formatRelativeTime(reviewViewerContent.review_timestamp || reviewViewerContent.reviewTimestamp)}
                  </span>
                  {reviewViewerContent.score !== null && reviewViewerContent.score !== undefined && (
                    <span className="mx-review-viewer__score">Score: {reviewViewerContent.score}/10</span>
                  )}
                </div>
                <Button variant="secondary" size="sm" onClick={handleCopy}>
                  {copySuccess ? '✓ Copied' : 'Copy Markdown'}
                </Button>
              </div>

              <div className="mx-review-viewer__content mx-markdown-body">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  rehypePlugins={[rehypeHighlight]}
                >
                  {reviewViewerContent.content || 'No content available'}
                </ReactMarkdown>
              </div>
            </>
          ) : null}
        </div>
        <div className="mx-draggable-modal__resize-handle" onMouseDown={onResizeStart} />
      </div>
    </div>
  )
}
