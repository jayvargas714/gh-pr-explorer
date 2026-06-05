import { useState } from 'react'
import { useReviewStore } from '../../stores/useReviewStore'
import { useAuditStore } from '../../stores/useAuditStore'
import { useAccountStore } from '../../stores/useAccountStore'
import { startReview, cancelReview, type ReviewerType } from '../../api/reviews'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import { ReviewerPickerMenu } from './ReviewerPickerMenu'
import type { PullRequest } from '../../api/types'

interface ReviewButtonProps {
  pr: PullRequest
}

export function ReviewButton({ pr }: ReviewButtonProps) {
  const [starting, setStarting] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const { activeReviews, updateReview, removeReview, showReviewError } =
    useReviewStore()
  const startAudit = useAuditStore((state) => state.startAudit)
  const cancelAudit = useAuditStore((state) => state.cancelAudit)
  const selectedRepo = useAccountStore((state) => state.selectedRepo)

  const owner = selectedRepo?.owner.login ?? ''
  const repo = selectedRepo?.name ?? ''
  const reviewKey = `${owner}/${repo}/${pr.number}`
  const review = activeReviews[reviewKey]
  const auditRunning = useAuditStore((state) => state.auditStatusFor(owner, repo, pr.number) === 'running')

  const handleStartReview = async (reviewerType: ReviewerType) => {
    if (starting || !owner || !repo) return
    setPickerOpen(false)

    if (reviewerType === 'audit') {
      if (auditRunning) return
      try {
        setStarting(true)
        await startAudit({
          number: pr.number,
          url: pr.url,
          owner,
          repo,
          title: pr.title,
          author: pr.author?.login,
          head_ref: pr.headRefName,
          base_ref: pr.baseRefName,
        })
      } catch (err) {
        console.error('Failed to start audit:', err)
      } finally {
        setStarting(false)
      }
      return
    }

    try {
      setStarting(true)
      const response = await startReview({
        number: pr.number,
        url: pr.url,
        owner,
        repo,
        reviewer_type: reviewerType,
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

  const handleCancelAudit = async () => {
    try {
      await cancelAudit(owner, repo, pr.number)
    } catch (err) {
      console.error('Failed to cancel audit:', err)
    }
  }

  const handleShowError = () => {
    if (!review) return
    showReviewError(
      pr.number,
      pr.title,
      pr.url,
      owner,
      repo,
      review.error_output || 'Unknown error',
      review.exit_code || null,
    )
  }

  // Audit running (only when no review is running for this PR)
  if (!review && auditRunning) {
    return (
      <Button variant="ghost" size="sm" onClick={handleCancelAudit}>
        <Spinner size="sm" /> Auditing… Cancel
      </Button>
    )
  }

  // No review running
  if (!review) {
    return (
      <div className="mx-reviewer-picker__wrapper">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setPickerOpen((open) => !open)}
          disabled={starting}
        >
          {starting ? <Spinner size="sm" /> : '📋 Review ▾'}
        </Button>
        {pickerOpen && (
          <ReviewerPickerMenu
            onSelect={handleStartReview}
            onClose={() => setPickerOpen(false)}
          />
        )}
      </div>
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
