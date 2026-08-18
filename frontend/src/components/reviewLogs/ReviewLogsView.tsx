import { Fragment, useEffect, useMemo, useState } from 'react'
import { useAccountStore } from '../../stores/useAccountStore'
import { fetchReviewLogs, fetchReviewLogStats } from '../../api/reviewLogs'
import { ReviewLogEvent, ReviewLogStats } from '../../api/types'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { formatRelativeTime } from '../../utils/formatters'

const EVENT_LABELS: Record<string, string> = {
  started: 'started',
  completed: 'completed',
  failed: 'attempt failed',
  retry_scheduled: 'retry scheduled',
  gave_up: 'gave up',
  cancelled: 'cancelled',
}

const REASON_LABELS: Record<string, string> = {
  no_output: 'exited 0 with no review written',
  nonzero_exit: 'CLI exited non-zero',
  spawn_failed: 'could not start the CLI',
  attempts_exhausted: 'all attempts used',
  cancelled: 'cancelled by user',
}

type BadgeVariant = 'success' | 'error' | 'warning' | 'info' | 'neutral'

function eventVariant(event: string): BadgeVariant {
  if (event === 'completed') return 'success'
  if (event === 'gave_up') return 'error'
  if (event === 'failed') return 'warning'
  if (event === 'retry_scheduled') return 'info'
  return 'neutral'
}

interface Run {
  runId: string
  prNumber: number
  repo: string
  events: ReviewLogEvent[]
  first: ReviewLogEvent
  last: ReviewLogEvent
  attempts: number
}

/**
 * Group a flat, newest-first event list into runs, preserving that ordering.
 *
 * A Map keeps insertion order, so runs come out ordered by their most recent
 * event — the same order the caller received them in.
 */
function groupIntoRuns(events: ReviewLogEvent[]): Run[] {
  const byRun = new Map<string, ReviewLogEvent[]>()
  events.forEach((event) => {
    const bucket = byRun.get(event.run_id)
    if (bucket) bucket.push(event)
    else byRun.set(event.run_id, [event])
  })

  return Array.from(byRun.entries()).map(([runId, runEvents]) => {
    // runEvents arrives newest-first, matching the API ordering.
    const last = runEvents[0]
    const first = runEvents[runEvents.length - 1]
    return {
      runId,
      prNumber: last.pr_number,
      repo: last.repo,
      events: runEvents,
      first,
      last,
      attempts: Math.max(...runEvents.map((e) => e.attempt || 1)),
    }
  })
}

export function ReviewLogsView() {
  const { selectedRepo } = useAccountStore()
  const [allRepos, setAllRepos] = useState(false)
  const [eventFilter, setEventFilter] = useState('')
  const [events, setEvents] = useState<ReviewLogEvent[]>([])
  const [stats, setStats] = useState<ReviewLogStats | null>(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  // review_events stores the repo as "owner/name"; the store holds an object.
  const repoSlug = selectedRepo
    ? `${selectedRepo.owner.login}/${selectedRepo.name}`
    : undefined
  const repoScope = allRepos ? undefined : repoSlug

  const load = async () => {
    try {
      setLoading(true)
      setError(null)
      const [logs, statsResponse] = await Promise.all([
        fetchReviewLogs({ repo: repoScope, event: eventFilter || undefined, limit: 500 }),
        fetchReviewLogStats({ repo: repoScope }),
      ])
      setEvents(logs.events)
      setTotal(logs.total)
      setStats(statsResponse.stats)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load review logs')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [repoScope, eventFilter])

  const runs = useMemo(() => groupIntoRuns(events), [events])

  const toggle = (runId: string) =>
    setExpanded((prev) => ({ ...prev, [runId]: !prev[runId] }))

  return (
    <div className="mx-review-logs">
      <div className="mx-review-logs__header">
        <h2>📜 Review Logs</h2>
        <div className="mx-review-logs__controls">
          <label className="mx-review-logs__toggle">
            <input
              type="checkbox"
              checked={allRepos}
              onChange={(e) => setAllRepos(e.target.checked)}
            />
            All repos
          </label>
          <select
            className="mx-review-logs__select"
            value={eventFilter}
            onChange={(e) => setEventFilter(e.target.value)}
          >
            <option value="">All events</option>
            {Object.entries(EVENT_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <Button onClick={load}>Refresh</Button>
        </div>
      </div>

      {stats && (
        <div className="mx-review-logs__stats">
          <div className="mx-review-logs__stat">
            <span className="mx-review-logs__stat-value">{stats.runs}</span>
            <span className="mx-review-logs__stat-label">runs</span>
          </div>
          <div className="mx-review-logs__stat">
            <span className="mx-review-logs__stat-value">{stats.completed}</span>
            <span className="mx-review-logs__stat-label">completed</span>
          </div>
          <div className="mx-review-logs__stat">
            <span className="mx-review-logs__stat-value">{stats.failed}</span>
            <span className="mx-review-logs__stat-label">gave up</span>
          </div>
          <div className="mx-review-logs__stat">
            <span className="mx-review-logs__stat-value">{stats.rescued_by_retry}</span>
            <span className="mx-review-logs__stat-label">saved by retry</span>
          </div>
          {Object.entries(stats.by_reason).map(([reason, count]) => (
            <div key={reason} className="mx-review-logs__stat mx-review-logs__stat--reason">
              <span className="mx-review-logs__stat-value">{count}</span>
              <span className="mx-review-logs__stat-label">{reason}</span>
            </div>
          ))}
        </div>
      )}

      {error && <Alert variant="error">{error}</Alert>}
      {loading && <Spinner />}

      {!loading && runs.length === 0 && (
        <div className="mx-empty-state">
          <h2>No review activity</h2>
          <p>Review starts, attempts and failures appear here as they happen.</p>
        </div>
      )}

      {!loading && runs.length > 0 && (
        <>
          <table className="mx-review-logs__table">
            <thead>
              <tr>
                <th></th>
                <th>PR</th>
                <th>Repo</th>
                <th>Started</th>
                <th>Latest</th>
                <th>Attempts</th>
                <th>Outcome</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <Fragment key={run.runId}>
                  <tr className="mx-review-logs__run" onClick={() => toggle(run.runId)}>
                    <td>{expanded[run.runId] ? '▾' : '▸'}</td>
                    <td>#{run.prNumber}</td>
                    <td>{run.repo}</td>
                    <td>{formatRelativeTime(run.first.created_at)}</td>
                    <td>{formatRelativeTime(run.last.created_at)}</td>
                    <td>{run.attempts}</td>
                    <td>
                      <Badge variant={eventVariant(run.last.event)}>
                        {EVENT_LABELS[run.last.event] || run.last.event}
                      </Badge>
                      {run.last.reason && (
                        <span className="mx-review-logs__reason">
                          {REASON_LABELS[run.last.reason] || run.last.reason}
                        </span>
                      )}
                    </td>
                  </tr>
                  {expanded[run.runId] &&
                    run.events.map((event) => (
                      <tr key={event.id} className="mx-review-logs__event">
                        <td></td>
                        <td colSpan={2}>
                          <Badge variant={eventVariant(event.event)}>
                            {EVENT_LABELS[event.event] || event.event}
                          </Badge>
                        </td>
                        <td colSpan={2}>{event.created_at}</td>
                        <td>{event.attempt ?? '—'}</td>
                        <td className="mx-review-logs__detail">
                          {event.reason && (
                            <div>{REASON_LABELS[event.reason] || event.reason}</div>
                          )}
                          {event.detail && <div><code>{event.detail}</code></div>}
                          {event.score !== null && <div>score {event.score}/10</div>}
                          {event.pid && <div>pid {event.pid}</div>}
                        </td>
                      </tr>
                    ))}
                </Fragment>
              ))}
            </tbody>
          </table>
          <p className="mx-review-logs__footer">
            {runs.length} run{runs.length === 1 ? '' : 's'} across {total} event
            {total === 1 ? '' : 's'}
          </p>
        </>
      )}
    </div>
  )
}
