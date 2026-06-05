import { useState } from 'react'
import { useAuditStore } from '../../stores/useAuditStore'
import { Modal } from '../common/Modal'
import { Alert } from '../common/Alert'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'

function getErrorExplanation(exitCode: number | null, errorOutput: string): string {
  const output = errorOutput.toLowerCase()
  if (output.includes('timeout') || output.includes('timed out'))
    return 'The audit process timed out. This can happen with very large PRs. Try again — if it persists, the PR may be too large for an automated audit.'
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
    return 'The audit process was killed (likely out of memory). This can happen with very large PRs.'
  return 'An unexpected error occurred during the audit process. Try again, and if the issue persists, check the error output for details.'
}

export function AuditErrorModal() {
  const { auditErrorModal, hideAuditError, cancelAudit, startAudit } = useAuditStore()
  const [retrying, setRetrying] = useState(false)
  const [dismissing, setDismissing] = useState(false)

  if (!auditErrorModal.show) return null

  const { prNumber, prTitle, prUrl, owner, repo, errorOutput, exitCode } = auditErrorModal

  // Clear the failed audit entry on the server so the picker button resets,
  // mirroring how a dismissed/cancelled review removes its active entry.
  const handleDismiss = async () => {
    if (dismissing) return
    try {
      setDismissing(true)
      if (prNumber && owner && repo) {
        await cancelAudit(owner, repo, prNumber).catch(() => {})
      }
    } finally {
      setDismissing(false)
      hideAuditError()
    }
  }

  const handleRetry = async () => {
    if (!prNumber || !owner || !repo || retrying) return
    try {
      setRetrying(true)
      // Drop the failed entry first so startAudit's optimistic 'running' sticks.
      await cancelAudit(owner, repo, prNumber).catch(() => {})
      await startAudit({ number: prNumber, url: prUrl, owner, repo })
      hideAuditError()
    } catch (err) {
      console.error('Failed to retry audit:', err)
    } finally {
      setRetrying(false)
    }
  }

  return (
    <Modal title={`Audit Failed - PR #${prNumber}`} onClose={handleDismiss} size="lg">
      <Alert variant="error">
        <strong>Audit process failed</strong>
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
          <Button variant="primary" onClick={handleRetry} disabled={retrying || dismissing}>
            {retrying ? <><Spinner size="sm" /> Retrying...</> : 'Retry Audit'}
          </Button>
          <Button variant="ghost" onClick={handleDismiss} disabled={dismissing || retrying}>
            {dismissing ? <><Spinner size="sm" /> Dismissing...</> : 'Dismiss'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
