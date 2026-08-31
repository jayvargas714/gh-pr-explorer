import { useCallback, useEffect, useState } from 'react'
import {
  enrollAutomationDispatch,
  listAutomationDispatches,
  optOutAutomationDispatch,
} from '../../api/automation'
import { AutomationDispatchRow, DispatchReviewState } from '../../api/types'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'

const PAGE_SIZES = [10, 25, 50, 100] as const

/** One compact cell answering "did a review run, is one running, and are we
 * waiting on new commits?" — the questions a bare dispatch row leaves open. */
function ReviewStateCell({ state }: { state: DispatchReviewState | null | undefined }) {
  if (!state) return <span>—</span>
  if (state.running) return <Badge size="sm" variant="info">▶ running now</Badge>

  const parts: string[] = []
  if (state.lastReviewStatus === 'completed') {
    parts.push(`✓ reviewed${state.isFollowup ? ' (follow-up)' : ''}`)
    if (state.score !== null) parts.push(`${state.score}/10`)
    if (state.verdictEvent && state.verdictOutcome === 'posted') {
      parts.push(state.verdictEvent === 'REQUEST_CHANGES' ? 'changes requested' : state.verdictEvent.toLowerCase())
    }
  } else if (state.lastReviewStatus === 'failed') {
    parts.push('✗ review failed')
  }
  if (state.armed) parts.push('armed — re-reviews on new commits')
  else if (state.lastReviewStatus) parts.push('not armed — no follow-ups')
  const tooltip = state.lastReviewAt
    ? `Last review: ${state.lastReviewAt.split('.')[0]} UTC`
    : undefined
  return (
    <span className="mx-automation__pipeline-review" data-tooltip={tooltip}>
      {parts.join(' · ')}
    </span>
  )
}

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
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZES[0])

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
    setPage(1)
    refresh(statusFilter)
  }, [refresh, statusFilter])

  const pendingCount = rows.filter((r) => r.status === 'pending').length

  // Clamp rather than store: a refresh that shrinks the list can strand the
  // saved page past the end.
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize))
  const currentPage = Math.min(page, totalPages)
  const pageRows = rows.slice((currentPage - 1) * pageSize, currentPage * pageSize)

  const [actingOn, setActingOn] = useState<string | null>(null)

  const act = async (row: AutomationDispatchRow, action: 'remove' | 'enroll') => {
    const key = `${row.repo}#${row.prNumber}`
    setActingOn(key)
    setError(null)
    try {
      if (action === 'remove') await optOutAutomationDispatch(row.repo, row.prNumber)
      else await enrollAutomationDispatch(row.repo, row.prNumber)
      await refresh(statusFilter)
    } catch (e) {
      setError(e instanceof Error ? e.message : `Failed to ${action} ${key}`)
    } finally {
      setActingOn(null)
    }
  }

  const rowAction = (row: AutomationDispatchRow) => {
    const key = `${row.repo}#${row.prNumber}`
    if (row.status === 'pending') {
      return (
        <Button size="sm" variant="danger" disabled={actingOn !== null}
                onClick={() => act(row, 'remove')}>
          {actingOn === key ? '…' : 'Remove'}
        </Button>
      )
    }
    if (row.status === 'skipped' || row.status === 'failed') {
      return (
        <Button size="sm" disabled={actingOn !== null} onClick={() => act(row, 'enroll')}>
          {actingOn === key ? '…' : 'Re-enroll'}
        </Button>
      )
    }
    return null
  }

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
        <>
          <table className="mx-automation__table">
            <thead>
              <tr>
                <th>PR</th>
                <th>Status</th>
                <th>Detail</th>
                <th>Review</th>
                <th>Reviewer</th>
                <th>Updated (UTC)</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {pageRows.map((row) => (
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
                  <td className="mx-automation__pipeline-detail"><ReviewStateCell state={row.reviewState} /></td>
                  <td>{row.reviewerKey || '—'}</td>
                  <td>{row.updatedAt}</td>
                  <td>{rowAction(row)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="mx-automation__pipeline-pager">
            <Button
              size="sm"
              variant="ghost"
              disabled={currentPage <= 1}
              onClick={() => setPage(currentPage - 1)}
              aria-label="Previous page"
            >
              ‹
            </Button>
            <span className="mx-automation__hint">
              Page {currentPage} of {totalPages} · {rows.length} PRs
            </span>
            <Button
              size="sm"
              variant="ghost"
              disabled={currentPage >= totalPages}
              onClick={() => setPage(currentPage + 1)}
              aria-label="Next page"
            >
              ›
            </Button>
            <select
              className="mx-select"
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value))
                setPage(1)
              }}
              aria-label="Rows per page"
            >
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>{n} / page</option>
              ))}
            </select>
          </div>
        </>
      )}
    </section>
  )
}
