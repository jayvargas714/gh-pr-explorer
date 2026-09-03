import { BulkAction, usePipelineStore } from '../../stores/usePipelineStore'
import { Button } from '../common/Button'

const ACTIONS: { key: BulkAction; label: string; tooltip: string; variant?: 'danger' }[] = [
  { key: 'optout', label: 'Opt out', tooltip: 'Remove waiting PRs from the pipeline (manual mode)', variant: 'danger' },
  { key: 'enroll', label: 'Re-enroll', tooltip: 'Put skipped/failed/opted-out PRs back into the pipeline' },
  { key: 'arm', label: 'Arm', tooltip: 'Arm auto verdict (keeps each PR’s reviewer and mode)' },
  { key: 'disarm', label: 'Disarm', tooltip: 'Disarm auto verdict' },
  { key: 'watch', label: 'Watch on board', tooltip: 'Add to the swimlane board’s default lane' },
]

const ACTION_PAST: Record<BulkAction, string> = {
  optout: 'Opted out',
  enroll: 'Re-enrolled',
  arm: 'Armed',
  disarm: 'Disarmed',
  watch: 'Watched',
}

/** Appears once any rows are selected; runs one action across the selection
 * with a done/failed counter. */
export function BulkActionBar() {
  const selection = usePipelineStore((s) => s.selection)
  const clearSelection = usePipelineStore((s) => s.clearSelection)
  const runBulk = usePipelineStore((s) => s.runBulk)
  const bulk = usePipelineStore((s) => s.bulk)
  const clearBulk = usePipelineStore((s) => s.clearBulk)

  if (selection.size === 0 && !bulk) return null
  const running = !!bulk?.running

  return (
    <div className="mx-pipe-bulk" role="toolbar" aria-label="Bulk actions">
      {selection.size > 0 && (
        <>
          <span className="mx-pipe-bulk__count">{selection.size} selected</span>
          {ACTIONS.map(({ key, label, tooltip, variant }) => (
            <Button
              key={key}
              variant={variant ?? 'secondary'}
              size="sm"
              disabled={running}
              onClick={() => runBulk(key, Array.from(selection))}
              data-tooltip={tooltip}
            >
              {label}
            </Button>
          ))}
          <Button variant="ghost" size="sm" onClick={clearSelection} disabled={running}>
            Clear selection
          </Button>
        </>
      )}
      {bulk && (
        <span
          className={'mx-pipe-bulk__progress' + (bulk.failed > 0 ? ' mx-pipe-bulk__progress--failed' : '')}
          aria-live="polite"
        >
          {running ? `${ACTION_PAST[bulk.action]}…` : ACTION_PAST[bulk.action]}{' '}
          {bulk.done}/{bulk.total}
          {bulk.failed > 0 && ` · ${bulk.failed} failed`}
          {!running && (
            <button
              type="button"
              className="mx-pipe-bulk__dismiss"
              onClick={clearBulk}
              aria-label="Dismiss"
            >
              ×
            </button>
          )}
        </span>
      )}
    </div>
  )
}
