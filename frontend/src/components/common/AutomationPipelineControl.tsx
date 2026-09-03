import { useEffect, useState } from 'react'
import { enrollAutomationDispatch, optOutAutomationDispatch } from '../../api/automation'
import { AutomationDispatchRow, AutomationDispatchState } from '../../api/types'
import { usePipelineStore } from '../../stores/usePipelineStore'
import { Badge } from './Badge'

/** PR-keyed so the same control renders on PR list cards, queue/board cards
 * and pipeline rows. `repo` is `owner/name`. */
interface AutomationPipelineControlProps {
  repo: string
  prNumber: number
  automation: AutomationDispatchState | null | undefined
  /** Closed/merged PRs can't be enrolled; hide the add button for them. */
  prState?: string
}

function rowToState(row: AutomationDispatchRow): AutomationDispatchState {
  return {
    status: row.status,
    reviewerKey: row.reviewerKey,
    ruleName: null,
    matchedRules: [],
    detail: row.detail,
    updatedAt: row.updatedAt,
  }
}

function pipelineBadge(automation: AutomationDispatchState) {
  switch (automation.status) {
    case 'unidentified':
      return (
        <span data-tooltip={`Automation couldn't pick a reviewer — files span: ${automation.matchedRules.join(', ') || 'no rules'}. Start the review manually.`}>
          <Badge variant="warning">❓ Unidentified</Badge>
        </span>
      )
    case 'dispatched':
      return (
        <span data-tooltip={`Auto-reviewed via ${automation.ruleName ?? 'default rule'} (${automation.reviewerKey})`}>
          <Badge variant="info">🤖 Auto</Badge>
        </span>
      )
    case 'failed':
      return (
        <span data-tooltip={`Automation gave up: ${automation.detail ?? 'unknown error'}`}>
          <Badge variant="error">🤖 Auto failed</Badge>
        </span>
      )
    case 'pending':
      return (
        <span data-tooltip={automation.detail ?? 'Waiting for dispatch conditions (CI, freshness, non-draft)'}>
          <Badge variant="neutral">⏳ Auto waiting</Badge>
        </span>
      )
    case 'skipped':
      return (
        <span data-tooltip={`Auto review skipped: ${automation.detail ?? 'no reason recorded'}`}>
          <Badge variant="neutral">🤖 Auto skipped</Badge>
        </span>
      )
    default:
      return null
  }
}

/** Automation pipeline badge plus the add/remove-from-pipeline control.
 *
 * Shared by PR list cards, queue/swimlane cards and pipeline rows so pipeline
 * membership is visible — and controllable — everywhere a PR appears. Waiting
 * PRs offer "remove" (manual opt-out); un-enrolled or skipped/failed PRs offer
 * "add"; dispatched/unidentified PRs are already handled, so only the badge
 * shows.
 */
export function AutomationPipelineControl({
  repo,
  prNumber,
  automation,
  prState,
}: AutomationPipelineControlProps) {
  // Server state arrives via list refreshes; toggles apply optimistically here.
  const [override, setOverride] = useState<AutomationDispatchState | null | undefined>(undefined)
  const [busy, setBusy] = useState(false)
  const patchRow = usePipelineStore((s) => s.patchRow)
  const setAutomationLocal = usePipelineStore((s) => s.setAutomationLocal)

  useEffect(() => {
    setOverride(undefined)
  }, [automation])

  const current = override !== undefined ? override : automation
  const canAdd =
    (prState === undefined || prState === 'OPEN') &&
    (!current || current.status === 'skipped' || current.status === 'failed')
  const canRemove = current?.status === 'pending'

  const toggle = async (e: React.MouseEvent) => {
    e.stopPropagation()
    e.preventDefault()
    if (busy) return
    setBusy(true)
    try {
      const resp = canRemove
        ? await optOutAutomationDispatch(repo, prNumber)
        : await enrollAutomationDispatch(repo, prNumber)
      const next = rowToState(resp.dispatch)
      setOverride(next)
      // Keep the pipeline overlay's copy in step (no-op when the PR isn't
      // in its rows yet — the next poll picks the new row up).
      if (resp.row) patchRow(resp.row)
      else setAutomationLocal(repo, prNumber, next)
    } catch {
      // Leave the rendered state as-is; the next list refresh is the truth.
    } finally {
      setBusy(false)
    }
  }

  if (!current && !canAdd) return null

  return (
    <span className="mx-auto-pipeline" onClick={(e) => e.stopPropagation()}>
      {current && pipelineBadge(current)}
      {(canAdd || canRemove) && (
        <button
          type="button"
          className="mx-auto-pipeline__toggle"
          disabled={busy}
          onClick={toggle}
          data-tooltip={canRemove
            ? 'Remove from the auto pipeline (manual mode)'
            : 'Add to the auto pipeline'}
          aria-label={canRemove ? 'Remove from auto pipeline' : 'Add to auto pipeline'}
        >
          {busy ? '…' : canRemove ? '🤖−' : '🤖+'}
        </button>
      )}
    </span>
  )
}
