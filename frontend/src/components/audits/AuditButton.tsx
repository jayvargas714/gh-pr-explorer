import { useState } from 'react'
import { useAuditStore } from '../../stores/useAuditStore'
import { useAccountStore } from '../../stores/useAccountStore'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import type { PullRequest } from '../../api/types'

interface AuditButtonProps {
  pr: PullRequest
}

export function AuditButton({ pr }: AuditButtonProps) {
  const [starting, setStarting] = useState(false)
  const startAudit = useAuditStore((state) => state.startAudit)
  const cancelAudit = useAuditStore((state) => state.cancelAudit)
  const showAuditError = useAuditStore((state) => state.showAuditError)
  const selectedRepo = useAccountStore((state) => state.selectedRepo)

  const owner = selectedRepo?.owner.login ?? ''
  const repo = selectedRepo?.name ?? ''
  const activeAudit = useAuditStore((state) =>
    state.activeAuditFor(owner, repo, pr.number),
  )
  const auditRunning = activeAudit?.status === 'running'
  const auditFailed = activeAudit?.status === 'failed'

  const handleStartAudit = async () => {
    if (starting || !owner || !repo || auditRunning) return
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
  }

  const handleCancelAudit = async () => {
    try {
      await cancelAudit(owner, repo, pr.number)
    } catch (err) {
      console.error('Failed to cancel audit:', err)
    }
  }

  const handleShowAuditError = () => {
    if (!activeAudit) return
    showAuditError(
      pr.number,
      pr.title,
      pr.url,
      owner,
      repo,
      activeAudit.error_output || 'Unknown error',
      activeAudit.exit_code ?? null,
    )
  }

  if (auditRunning) {
    return (
      <Button variant="ghost" size="sm" onClick={handleCancelAudit}>
        <Spinner size="sm" /> Auditing… Cancel
      </Button>
    )
  }

  if (auditFailed) {
    return (
      <Button variant="ghost" size="sm" onClick={handleShowAuditError}>
        ✗ Audit Error
      </Button>
    )
  }

  return (
    <Button variant="ghost" size="sm" onClick={handleStartAudit} disabled={starting}>
      {starting ? <Spinner size="sm" /> : '🔎 Audit'}
    </Button>
  )
}
