import { useEffect, useState } from 'react'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { useReviewStore } from '../../stores/useReviewStore'
import { useUIStore } from '../../stores/useUIStore'
import { fetchReviewHistory } from '../../api/reviews'
import { Button } from '../common/Button'
import { Input } from '../common/Input'
import { Badge } from '../common/Badge'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'
import { formatRelativeTime } from '../../utils/formatters'

export function HistoryPanel() {
  const showHistoryPanel = useUIStore((state) => state.showHistoryPanel)
  const setShowHistoryPanel = useUIStore((state) => state.setShowHistoryPanel)
  const { openReviewViewer } = useReviewStore()
  const {
    searchQuery,
    setSearchQuery,
    prNumberFilter,
    setPRNumberFilter,
    resetFilters,
  } = useHistoryStore()
  const [reviews, setReviews] = useState<any[]>([])
  const [totalReviews, setTotalReviews] = useState<number>(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (showHistoryPanel) {
      loadHistory()
    }
  }, [showHistoryPanel, searchQuery, prNumberFilter])

  const loadHistory = async () => {
    try {
      setLoading(true)
      setError(null)
      const params: Record<string, any> = {}
      if (searchQuery) params.search = searchQuery
      if (prNumberFilter) params.pr_number = prNumberFilter
      const response = await fetchReviewHistory(params)
      setReviews(response.reviews)
      if (response.total !== undefined) setTotalReviews(response.total)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load review history')
    } finally {
      setLoading(false)
    }
  }

  const handleViewReview = (review: any) => {
    openReviewViewer(review)
  }

  const getScoreBadge = (score: number | null) => {
    if (score === null || score === undefined) return null
    if (score >= 7) return <Badge variant="success">{score}/10</Badge>
    if (score >= 4) return <Badge variant="warning">{score}/10</Badge>
    return <Badge variant="error">{score}/10</Badge>
  }

  if (!showHistoryPanel) return null

  return (
    <>
      {/* Overlay */}
      <div className="mx-history-overlay" onClick={() => setShowHistoryPanel(false)} />

      {/* Panel */}
      <div className="mx-history-panel">
        <div className="mx-history-panel__header">
          <div className="mx-history-panel__title">
            <h2>Review History</h2>
            <span className="mx-history-panel__count">
              {totalReviews} total {totalReviews === 1 ? 'review' : 'reviews'}
            </span>
          </div>
          <Button variant="ghost" size="sm" onClick={() => setShowHistoryPanel(false)}>
            ✕
          </Button>
        </div>

        <div className="mx-history-panel__total">
          Total PRs Reviewed: <strong>{totalReviews}</strong>
        </div>

        <div className="mx-history-panel__filters">
          <Input
            label="Search"
            placeholder="Search reviews..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />

          <Input
            label="PR Number"
            type="number"
            placeholder="Filter by PR #"
            value={prNumberFilter}
            onChange={(e) => setPRNumberFilter(e.target.value)}
          />

          <Button variant="secondary" size="sm" onClick={resetFilters}>
            Reset
          </Button>
        </div>

        <div className="mx-history-panel__content">
          {loading && reviews.length === 0 ? (
            <div className="mx-history-panel__loading">
              <Spinner size="md" />
              <p>Loading history...</p>
            </div>
          ) : error ? (
            <Alert variant="error">{error}</Alert>
          ) : reviews.length === 0 ? (
            <Alert variant="info">No reviews found matching the current filters.</Alert>
          ) : (
            <div className="mx-history-panel__list">
              {reviews.map((review) => (
                <div key={review.id} className="mx-history-item" onClick={() => handleViewReview(review)}>
                  <div className="mx-history-item__header">
                    <span className="mx-history-item__pr">
                      #{review.pr_number} {review.pr_title}
                    </span>
                    {getScoreBadge(review.score)}
                  </div>
                  <div className="mx-history-item__meta">
                    <span className="mx-history-item__repo">{review.repo}</span>
                    <span className="mx-history-item__author">by {review.pr_author}</span>
                    <span className="mx-history-item__time">
                      {formatRelativeTime(review.review_timestamp)}
                    </span>
                  </div>
                  {review.is_followup && (
                    <Badge variant="info" size="sm">
                      Follow-up
                    </Badge>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
