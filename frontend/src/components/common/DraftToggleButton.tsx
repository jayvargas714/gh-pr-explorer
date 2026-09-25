import { useEffect, useState } from 'react'
import { setPRDraft } from '../../api/prs'
import { Button } from './Button'

interface DraftToggleButtonProps {
  /** `owner/name` */
  repo: string
  prNumber: number
  isDraft: boolean
  prState: string | null | undefined
  /** Called after GitHub accepted the change, so the host can refresh its data. */
  onDone?: () => void
}

/** "✓ Ready" on drafts, "✎ Draft" on open PRs; nothing for closed/merged. */
export function DraftToggleButton({ repo, prNumber, isDraft, prState, onDone }: DraftToggleButtonProps) {
  // Applied after GitHub accepts the change so the label flips before the host refresh lands.
  const [override, setOverride] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setOverride(null)
  }, [isDraft])

  if (prState !== 'OPEN') return null
  const draft = override ?? isDraft

  const toggle = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (busy) return
    const [owner, name] = repo.split('/')
    setBusy(true)
    setError(null)
    try {
      const resp = await setPRDraft(owner, name, prNumber, !draft)
      setOverride(resp.isDraft)
      onDone?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Draft toggle failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="mx-pr-action" onClick={(e) => e.stopPropagation()}>
      <Button
        variant="ghost"
        size="sm"
        onClick={toggle}
        disabled={busy}
        data-tooltip={draft ? 'Mark ready for review' : 'Convert to draft'}
      >
        {busy ? '…' : draft ? '✓ Ready' : '✎ Draft'}
      </Button>
      {error && (
        <span className="mx-pr-action__error" data-tooltip={error} role="alert">
          ⚠
        </span>
      )}
    </span>
  )
}
