import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import { useReviewStore } from '../../stores/useReviewStore'
import { fetchReviewById } from '../../api/reviews'
import { Modal } from '../common/Modal'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'
import { formatRelativeTime } from '../../utils/formatters'
import type { Review } from '../../api/types'

export function ReviewViewer() {
  const { showReviewViewer, reviewViewerContent, setShowReviewViewer, setReviewViewerContent } =
    useReviewStore()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copySuccess, setCopySuccess] = useState(false)

  useEffect(() => {
    if (showReviewViewer && reviewViewerContent?.id) {
      loadReview(reviewViewerContent.id)
    }
  }, [showReviewViewer, reviewViewerContent?.id])

  const loadReview = async (reviewId: number) => {
    try {
      setLoading(true)
      setError(null)
      const review = await fetchReviewById(reviewId)
      setReviewViewerContent(review)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load review')
    } finally {
      setLoading(false)
    }
  }

  const handleClose = () => {
    setShowReviewViewer(false)
    setReviewViewerContent(null)
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

  return (
    <Modal
      title={`Code Review - PR #${reviewViewerContent?.pr_number || ''}`}
      onClose={handleClose}
      size="xl"
    >
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
                href={reviewViewerContent.pr_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mx-review-viewer__pr-link"
              >
                {reviewViewerContent.pr_title}
              </a>
              <span className="mx-review-viewer__time">
                Reviewed {formatRelativeTime(reviewViewerContent.review_timestamp)}
              </span>
              {reviewViewerContent.score !== null && reviewViewerContent.score !== undefined && (
                <span className="mx-review-viewer__score">Score: {reviewViewerContent.score}/10</span>
              )}
            </div>
            <Button variant="secondary" size="sm" onClick={handleCopy}>
              {copySuccess ? '✓ Copied' : '📋 Copy Markdown'}
            </Button>
          </div>

          <div className="mx-review-viewer__content">
            <ReactMarkdown>{reviewViewerContent.content || 'No content available'}</ReactMarkdown>
          </div>
        </>
      ) : null}
    </Modal>
  )
}
