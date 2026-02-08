import { useState } from 'react'
import { useReviewStore } from '../../stores/useReviewStore'
import { startReview, cancelReview } from '../../api/reviews'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import type { PullRequest } from '../../api/types'

interface ReviewButtonProps {
  pr: PullRequest
}

export function ReviewButton({ pr }: ReviewButtonProps) {
  const [starting, setStarting] = useState(false)
  const { activeReviews, addActiveReview, removeActiveReview, setReviewErrorModal } =
    useReviewStore()

  const reviewKey = `${pr.base.repo.owner.login}/${pr.base.repo.name}/${pr.number}`
  const review = activeReviews[reviewKey]

  const handleStartReview = async () => {
    if (starting) return

    try {
      setStarting(true)
      const response = await startReview({
        number: pr.number,
        url: pr.url,
        owner: pr.base.repo.owner.login,
        repo: pr.base.repo.name,
      })
      addActiveReview(reviewKey, response)
    } catch (err) {
      console.error('Failed to start review:', err)
    } finally {
      setStarting(false)
    }
  }

  const handleCancelReview = async () => {
    try {
      await cancelReview(pr.base.repo.owner.login, pr.base.repo.name, pr.number)
      removeActiveReview(reviewKey)
    } catch (err) {
      console.error('Failed to cancel review:', err)
    }
  }

  const handleShowError = () => {
    if (!review) return
    setReviewErrorModal({
      show: true,
      prNumber: pr.number,
      prTitle: pr.title,
      errorOutput: review.error_output || 'Unknown error',
      exitCode: review.exit_code || null,
    })
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
