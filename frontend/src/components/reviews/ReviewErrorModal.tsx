import { useState } from 'react'
import { useReviewStore } from '../../stores/useReviewStore'
import { startReview } from '../../api/reviews'
import { Modal } from '../common/Modal'
import { Alert } from '../common/Alert'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'

function getErrorExplanation(exitCode: number | null, errorOutput: string): string {
  const output = errorOutput.toLowerCase()
  if (output.includes('timeout') || output.includes('timed out'))
    return 'The review process timed out. This can happen with very large PRs. Try again — if it persists, the PR may be too large for automated review.'
  if (output.includes('rate limit') || output.includes('429'))
    return 'API rate limit exceeded. Wait a few minutes and try again.'
  if (output.includes('not found') || output.includes('404'))
    return 'The PR or repository could not be found. It may have been deleted or you may not have access.'
  if (output.includes('permission') || output.includes('403') || output.includes('unauthorized'))
    return 'Permission denied. Check that your GitHub CLI authentication is current (run `gh auth status`).'
  if (output.includes('network') || output.includes('connection'))
    return 'Network error. Check your internet connection and try again.'
  if (output.includes('claude') && output.includes('not found'))
    return 'Claude CLI not found. Make sure it is installed and available on your PATH.'
  if (exitCode === 1)
    return 'The Claude CLI process exited with an error. This is often a transient issue — retrying usually works.'
  if (exitCode === 137 || exitCode === 139)
    return 'The review process was killed (likely out of memory). This can happen with very large PRs.'
  return 'An unexpected error occurred during the review process. Try again, and if the issue persists, check the error output for details.'
}

export function ReviewErrorModal() {
  const { reviewErrorModal, hideReviewError, updateReview, removeReview } = useReviewStore()
  const [retrying, setRetrying] = useState(false)

  if (!reviewErrorModal.show) return null

  const { prNumber, prTitle, prUrl, owner, repo, errorOutput, exitCode } = reviewErrorModal

  const handleRetry = async () => {
    if (!prNumber || !owner || !repo || retrying) return

    const reviewKey = `${owner}/${repo}/${prNumber}`
    try {
      setRetrying(true)
      removeReview(reviewKey)
      await startReview({ number: prNumber, url: prUrl, owner, repo })
      updateReview(reviewKey, {
        key: reviewKey,
        owner,
        repo,
        pr_number: prNumber,
        status: 'running',
        started_at: new Date().toISOString(),
        completed_at: null,
        pr_url: prUrl,
        review_file: '',
        exit_code: null,
        error_output: '',
      })
      hideReviewError()
    } catch (err) {
      console.error('Failed to retry review:', err)
    } finally {
      setRetrying(false)
    }
  }

  return (
    <Modal title={`Review Failed - PR #${prNumber}`} onClose={hideReviewError} size="lg">
      <Alert variant="error">
        <strong>Review process failed</strong>
        {exitCode !== null && <> (exit code: {exitCode})</>}
      </Alert>

      <div className="mx-review-error__details">
        <h3>PR Details</h3>
        <p>{prTitle}</p>

        <h3>What Happened</h3>
        <p className="mx-review-error__explanation">
          {getErrorExplanation(exitCode, errorOutput)}
        </p>

        <h3>Error Output</h3>
        <pre className="mx-review-error__output">{errorOutput || 'No error output available'}</pre>

        <div className="mx-review-error__actions">
          <Button variant="primary" onClick={handleRetry} disabled={retrying}>
            {retrying ? <><Spinner size="sm" /> Retrying...</> : 'Retry Review'}
          </Button>
          <Button variant="ghost" onClick={hideReviewError}>
            Dismiss
          </Button>
        </div>
      </div>
    </Modal>
  )
}
