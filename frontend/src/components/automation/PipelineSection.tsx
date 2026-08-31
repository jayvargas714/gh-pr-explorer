import { useCallback, useEffect, useState } from 'react'
import { listAutomationDispatches } from '../../api/automation'
import { AutomationDispatchRow } from '../../api/types'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'

const STATUS_VARIANTS: Record<AutomationDispatchRow['status'], 'success' | 'error' | 'warning' | 'info' | 'neutral'> = {
  pending: 'warning',
  dispatched: 'success',
  unidentified: 'info',
  skipped: 'neutral',
  failed: 'error',
}

const STATUS_FILTERS = ['all', 'pending', 'dispatched', 'unidentified', 'skipped', 'failed'] as const

/** Read-only view of the automation pipeline: every PR the pipeline is
 * holding or has handled, so the operator can see PRs progressing toward
 * dispatch (drafts included — they wait here without appearing on the board). */
export function PipelineSection() {
  const [rows, setRows] = useState<AutomationDispatchRow[]>([])
  const [statusFilter, setStatusFilter] = useState<(typeof STATUS_FILTERS)[number]>('all')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async (filter: typeof statusFilter) => {
    setLoading(true)
    setError(null)
    try {
      const resp = await listAutomationDispatches(filter === 'all' ? undefined : [filter])
      setRows(resp.dispatches)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load the pipeline')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh(statusFilter)
  }, [refresh, statusFilter])

  const pendingCount = rows.filter((r) => r.status === 'pending').length

  return (
    <section className="mx-automation__section">
      <h3 className="mx-automation__section-title">Pipeline</h3>
      <p className="mx-automation__intro">
        PRs the automation pipeline is holding or has handled. Waiting PRs are
        re-checked continuously until their conditions hold or the PR closes;
        drafts wait here without appearing on the swimlane board.
      </p>

      <div className="mx-automation__pipeline-toolbar">
        <select
          className="mx-select"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as (typeof STATUS_FILTERS)[number])}
          aria-label="Filter pipeline by status"
        >
          {STATUS_FILTERS.map((s) => (
            <option key={s} value={s}>{s === 'all' ? 'All statuses' : s}</option>
          ))}
        </select>
        {statusFilter === 'all' && rows.length > 0 && (
          <span className="mx-automation__hint">{pendingCount} waiting · {rows.length} shown</span>
        )}
        <Button size="sm" onClick={() => refresh(statusFilter)} disabled={loading}>
          {loading ? 'Loading…' : 'Refresh'}
        </Button>
      </div>

      {error && <p className="mx-automation__pipeline-error">{error}</p>}

      {rows.length === 0 && !loading && !error ? (
        <p className="mx-automation__hint">The pipeline is empty.</p>
      ) : (
        <table className="mx-automation__table">
          <thead>
            <tr>
              <th>PR</th>
              <th>Status</th>
              <th>Detail</th>
              <th>Reviewer</th>
              <th>Updated (UTC)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.repo}#${row.prNumber}`}>
                <td>
                  <a
                    href={`https://github.com/${row.repo}/pull/${row.prNumber}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {row.repo}#{row.prNumber}
                  </a>
                </td>
                <td><Badge size="sm" variant={STATUS_VARIANTS[row.status]}>{row.status}</Badge></td>
                <td className="mx-automation__pipeline-detail">{row.detail || '—'}</td>
                <td>{row.reviewerKey || '—'}</td>
                <td>{row.updatedAt}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
