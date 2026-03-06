import { useState, useEffect, useRef } from 'react'
import { useReviewStore } from '../../stores/useReviewStore'
import { startReview, cancelReview } from '../../api/reviews'
import { InlineIssuePickerModal } from './InlineIssuePickerModal'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import type { MergeQueueItem } from '../../api/types'

interface QueueReviewButtonProps {
  item: MergeQueueItem
  onRefresh: () => void
}

export function QueueReviewButton({ item, onRefresh }: QueueReviewButtonProps) {
  const [starting, setStarting] = useState(false)
  const [pickerSection, setPickerSection] = useState<string | null>(null)
  const { activeReviews, updateReview, removeReview, showReviewError } = useReviewStore()

  const [owner, repo] = item.repo.split('/')
  const reviewKey = `${item.repo}/${item.number}`
  const review = activeReviews[reviewKey]
  const prevStatusRef = useRef(review?.status)

  // Refresh queue when a review transitions to completed or failed
  useEffect(() => {
    const prevStatus = prevStatusRef.current
    const currStatus = review?.status
    prevStatusRef.current = currStatus

    if (prevStatus === 'running' && (currStatus === 'completed' || currStatus === 'failed')) {
      onRefresh()
    }
  }, [review?.status, onRefresh])

  const handleStartReview = async () => {
    if (starting || !owner || !repo) return

    try {
      setStarting(true)
      await startReview({
        number: item.number,
        url: item.url,
        owner,
        repo,
        title: item.title,
        author: item.author,
        is_followup: item.hasReview,
        previous_review_id: item.reviewId ?? undefined,
      })
      updateReview(reviewKey, {
        key: reviewKey,
        owner,
        repo,
        pr_number: item.number,
        status: 'running',
        started_at: new Date().toISOString(),
        completed_at: null,
        pr_url: item.url,
        review_file: '',
        exit_code: null,
        error_output: '',
      })
    } catch (err) {
      console.error('Failed to start review:', err)
    } finally {
      setStarting(false)
    }
  }

  const handleCancelReview = async () => {
    try {
      await cancelReview(owner, repo, item.number)
      removeReview(reviewKey)
    } catch (err) {
      console.error('Failed to cancel review:', err)
    }
  }

  const handleShowError = () => {
    if (!review) return
    showReviewError(
      item.number,
      item.title,
      review.error_output || 'Unknown error',
      review.exit_code || null,
    )
  }

  const handleSectionPosted = () => {
    setPickerSection(null)
    onRefresh()
  }

  // Review in progress
  if (review?.status === 'running') {
    return (
      <Button variant="ghost" size="sm" onClick={handleCancelReview}>
        <Spinner size="sm" /> Cancel
      </Button>
    )
  }

  // Review failed
  if (review?.status === 'failed') {
    return (
      <Button variant="ghost" size="sm" onClick={handleShowError}>
        ✗ Error
      </Button>
    )
  }

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        onClick={handleStartReview}
        disabled={starting}
      >
        {starting ? <Spinner size="sm" /> : item.hasReview ? '🔄 Re-review' : '📋 Review'}
      </Button>

      {item.hasReview && item.reviewId && !item.inlineCommentsPosted && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setPickerSection('critical')}
          data-tooltip="Select and post critical issues as inline comments"
        >
          🔴 Critical
        </Button>
      )}

      {item.hasReview && item.reviewId && !item.majorConcernsPosted && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setPickerSection('major')}
          data-tooltip="Select and post major concerns as inline comments"
        >
          🟡 Major
        </Button>
      )}

      {item.hasReview && item.reviewId && !item.minorIssuesPosted && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setPickerSection('minor')}
          data-tooltip="Select and post minor issues as inline comments"
        >
          🟢 Minor
        </Button>
      )}

      {pickerSection && item.reviewId && (
        <InlineIssuePickerModal
          reviewId={item.reviewId}
          section={pickerSection}
          onClose={() => setPickerSection(null)}
          onPosted={handleSectionPosted}
        />
      )}
    </>
  )
}
