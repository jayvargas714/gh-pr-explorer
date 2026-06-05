import { useState } from 'react'
import { useAuditStore } from '../../stores/useAuditStore'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'

interface AuditButtonProps {
  owner: string
  repo: string
  number: number
  url: string
  title?: string
  author?: string
  headRef?: string
  baseRef?: string
}

export function AuditButton({
  owner,
  repo,
  number,
  url,
  title,
  author,
  headRef,
  baseRef,
}: AuditButtonProps) {
  const [starting, setStarting] = useState(false)
  const startAudit = useAuditStore((state) => state.startAudit)
  const cancelAudit = useAuditStore((state) => state.cancelAudit)
  const showAuditError = useAuditStore((state) => state.showAuditError)

  const activeAudit = useAuditStore((state) =>
    state.activeAuditFor(owner, repo, number),
  )
  const auditRunning = activeAudit?.status === 'running'
  const auditFailed = activeAudit?.status === 'failed'

  const handleStartAudit = async () => {
    if (starting || !owner || !repo || auditRunning) return
    try {
      setStarting(true)
      await startAudit({
        number,
        url,
        owner,
        repo,
        title,
        author,
        head_ref: headRef,
        base_ref: baseRef,
      })
    } catch (err) {
      console.error('Failed to start audit:', err)
    } finally {
      setStarting(false)
    }
  }

  const handleCancelAudit = async () => {
    try {
      await cancelAudit(owner, repo, number)
    } catch (err) {
      console.error('Failed to cancel audit:', err)
    }
  }

  const handleShowAuditError = () => {
    if (!activeAudit) return
    showAuditError(
      number,
      title ?? '',
      url,
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
