import { useState } from 'react'
import { useReviewStore } from '../../stores/useReviewStore'
import { useAccountStore } from '../../stores/useAccountStore'
import { startReview, cancelReview } from '../../api/reviews'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import type { PullRequest } from '../../api/types'

interface ReviewButtonProps {
  pr: PullRequest
}

export function ReviewButton({ pr }: ReviewButtonProps) {
  const [starting, setStarting] = useState(false)
  const { activeReviews, updateReview, removeReview, showReviewError } =
    useReviewStore()
  const selectedRepo = useAccountStore((state) => state.selectedRepo)

  const owner = selectedRepo?.owner.login ?? ''
  const repo = selectedRepo?.name ?? ''
  const reviewKey = `${owner}/${repo}/${pr.number}`
  const review = activeReviews[reviewKey]

  const handleStartReview = async () => {
    if (starting || !owner || !repo) return

    try {
      setStarting(true)
      const response = await startReview({
        number: pr.number,
        url: pr.url,
        owner,
        repo,
      })
      updateReview(reviewKey, {
        key: reviewKey,
        owner,
        repo,
        pr_number: pr.number,
        status: 'running',
        started_at: new Date().toISOString(),
        completed_at: null,
        pr_url: pr.url,
        review_file: response.key || '',
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
      await cancelReview(owner, repo, pr.number)
      removeReview(reviewKey)
    } catch (err) {
      console.error('Failed to cancel review:', err)
    }
  }

  const handleShowError = () => {
    if (!review) return
    showReviewError(
      pr.number,
      pr.title,
      review.error_output || 'Unknown error',
      review.exit_code || null,
    )
  }

  // No review running
  if (!review) {
    return (
      <Button variant="ghost" size="sm" onClick={handleStartReview} disabled={starting}>
        {starting ? <Spinner size="sm" /> : '📋 Review'}
      </Button>
    )
  }

  // Review running
  if (review.status === 'running') {
    return (
      <Button variant="ghost" size="sm" onClick={handleCancelReview}>
        <Spinner size="sm" /> Cancel
      </Button>
    )
  }

  // Review completed
  if (review.status === 'completed') {
    return (
      <Button variant="ghost" size="sm" disabled>
        ✓ Reviewed
      </Button>
    )
  }

  // Review failed
  if (review.status === 'failed') {
    return (
      <Button variant="ghost" size="sm" onClick={handleShowError}>
        ✗ Error
      </Button>
    )
  }

  return null
}
