import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { useAccountStore } from '../../stores/useAccountStore'
import { fetchReviewLogs, fetchReviewLogStats } from '../../api/reviewLogs'
import { fetchActiveReviews } from '../../api/reviews'
import { Review, ReviewIssueCounts, ReviewLogEvent, ReviewLogStats } from '../../api/types'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import {
  formatClockTime,
  formatDuration,
  formatFullDateTime,
  formatShortDate,
} from '../../utils/formatters'

const EVENT_LABELS: Record<string, string> = {
  started: 'started',
  completed: 'completed',
  failed: 'attempt failed',
  retry_scheduled: 'retry scheduled',
  gave_up: 'gave up',
  cancelled: 'cancelled',
  verdict_posted: 'verdict posted',
  verdict_not_posted: 'verdict not posted',
}

const REASON_LABELS: Record<string, string> = {
  no_output: 'exited 0 with no review written',
  nonzero_exit: 'CLI exited non-zero',
  spawn_failed: 'could not start the CLI',
  attempts_exhausted: 'all attempts used',
  cancelled: 'cancelled by user',
  stale_commits: 'stopped: new commits made the review stale',
  orphaned: 'lost in a service restart',
  auto_suppressed: 'suppressed by criteria',
  auto_skipped: 'not eligible',
  post_failed: 'GitHub rejected the post',
}

type BadgeVariant = 'success' | 'error' | 'warning' | 'info' | 'neutral'

function eventVariant(event: string): BadgeVariant {
  if (event === 'completed' || event === 'verdict_posted') return 'success'
  if (event === 'gave_up') return 'error'
  if (event === 'failed' || event === 'verdict_not_posted') return 'warning'
  if (event === 'retry_scheduled') return 'info'
  return 'neutral'
}

// Whether a verdict reached GitHub is a separate axis from how the review run
// itself ended, so these events are held out of the run's Outcome column and
// summarised in Posted instead.
const VERDICT_EVENTS = new Set(['verdict_posted', 'verdict_not_posted'])

interface Run {
  runId: string
  prNumber: number
  repo: string
  events: ReviewLogEvent[]
  first: ReviewLogEvent
  /** Latest lifecycle event — what the run's Outcome column reports. */
  last: ReviewLogEvent
  /** Latest verdict event, if the run's review ever reached a posting decision. */
  verdict: ReviewLogEvent | null
  attempts: number
  /** Issue tally of the review this run produced; null when it produced none. */
  issueCounts: ReviewIssueCounts | null
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
    const lifecycle = runEvents.filter((e) => !VERDICT_EVENTS.has(e.event))
    // Fall back to the raw list when an event filter has left nothing else.
    const last = lifecycle[0] ?? runEvents[0]
    const first = runEvents[runEvents.length - 1]
    return {
      runId,
      prNumber: last.pr_number,
      repo: last.repo,
      events: runEvents,
      first,
      last,
      verdict: runEvents.find((e) => VERDICT_EVENTS.has(e.event)) ?? null,
      attempts: Math.max(...lifecycle.map((e) => e.attempt || 1), 1),
      issueCounts: runEvents.find((e) => e.issue_counts)?.issue_counts ?? null,
    }
  })
}

interface DayStats {
  runs: number
  completed: number
  gaveUp: number
  posted: number
}

interface DayGroup {
  /** Local calendar day, `YYYY-MM-DD`. */
  key: string
  /** Any timestamp from that day, for formatting the header. */
  date: string
  runs: Run[]
  stats: DayStats
}

/**
 * Local calendar day for a timestamp.
 *
 * Built from the local getters rather than `toISOString().slice(0, 10)`, which
 * buckets by UTC and would file a late-evening run under the following day for
 * anyone west of Greenwich.
 */
function localDayKey(dateString: string): string {
  const d = new Date(dateString)
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${month}-${day}`
}

/**
 * Bucket runs into calendar days, newest day first.
 *
 * Runs are sorted by when they *started*, not by their latest event: that is
 * what "reviews done that day" means, and it is what keeps each day's header
 * contiguous. Ordering by latest event would let a run started yesterday and
 * retried today sit in today's slot under a yesterday header, heading the same
 * date twice.
 *
 * Day counts are derived from the same `last` / `verdict` fields the Outcome and
 * Posted columns render, so a header can never disagree with its own rows.
 */
function groupIntoDays(runs: Run[]): DayGroup[] {
  const byDay = new Map<string, Run[]>()
  const sorted = [...runs].sort(
    (a, b) => new Date(b.first.created_at).getTime() - new Date(a.first.created_at).getTime(),
  )

  sorted.forEach((run) => {
    const key = localDayKey(run.first.created_at)
    const bucket = byDay.get(key)
    if (bucket) bucket.push(run)
    else byDay.set(key, [run])
  })

  return Array.from(byDay.entries()).map(([key, dayRuns]) => ({
    key,
    date: dayRuns[0].first.created_at,
    runs: dayRuns,
    stats: {
      runs: dayRuns.length,
      completed: dayRuns.filter((r) => r.last.event === 'completed').length,
      gaveUp: dayRuns.filter((r) => r.last.event === 'gave_up').length,
      posted: dayRuns.filter((r) => r.verdict?.event === 'verdict_posted').length,
    },
  }))
}

/**
 * The day-navigation neighbours of a selected day.
 *
 * `dayKeys` is newest-first, and `YYYY-MM-DD` keys compare chronologically as
 * strings. A null selection means the newest day. The selected key need not be
 * in the list — the calendar can land on a day with no runs — in which case
 * each arrow targets the nearest day with runs on its side, so the user can
 * always step out of an empty day.
 */
function navTargets(
  dayKeys: string[],
  selectedKey: string | null,
): { older: string | null; newer: string | null } {
  if (dayKeys.length === 0) return { older: null, newer: null }
  const key = selectedKey ?? dayKeys[0]
  const greater = dayKeys.filter((k) => k > key)
  return {
    older: dayKeys.find((k) => k < key) ?? null,
    newer: greater.length > 0 ? greater[greater.length - 1] : null,
  }
}

/**
 * Format a `YYYY-MM-DD` day key like "Mon, Aug 25, 2026".
 *
 * Parsed field-by-field: `new Date('2026-08-25')` is UTC midnight, which
 * `toLocaleDateString` would render as the *previous* day west of Greenwich.
 */
function formatDayLabel(key: string): string {
  const [year, month, day] = key.split('-').map(Number)
  return new Date(year, month - 1, day).toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

/**
 * Day header row. Zero-valued counts are dropped so a clean day reads clean.
 *
 * `partial` marks the oldest day when the page cut off mid-day: its counts are
 * of what loaded, not of what happened, and a header that quietly understates a
 * day is worse than one that admits it.
 */
function DayRow({ group, partial }: { group: DayGroup; partial?: boolean }) {
  const { stats } = group
  const parts = [
    `${partial ? '≥' : ''}${stats.runs} run${stats.runs === 1 ? '' : 's'}`,
    stats.completed > 0 ? `${stats.completed} completed` : null,
    stats.gaveUp > 0 ? `${stats.gaveUp} gave up` : null,
    stats.posted > 0 ? `${stats.posted} posted` : null,
  ].filter(Boolean)

  return (
    <tr className="mx-review-logs__day">
      <td colSpan={8}>
        <span className="mx-review-logs__day-date">{formatShortDate(group.date)}</span>
        <span className="mx-review-logs__day-stats">{parts.join(' · ')}</span>
        {partial && (
          <span
            className="mx-review-logs__day-partial"
            title="Older events beyond this page were not loaded, so this day is incomplete"
          >
            partial day
          </span>
        )}
      </td>
    </tr>
  )
}

/**
 * Build the hover panel for a run.
 *
 * Rendered through the app's global TooltipProvider, whose portal is styled
 * `white-space: pre-line` — so newlines here become real line breaks and the
 * panel escapes the table's overflow container for free.
 *
 * A run that produced no review has no counts to show, so it reports why it
 * ended instead: that is exactly the row you most want to inspect on hover.
 */
function runTooltip(run: Run): string {
  const lines: string[] = []

  if (run.issueCounts) {
    const { critical, major, minor } = run.issueCounts
    lines.push(`${critical} critical · ${major} major · ${minor} minor`)
  } else if (run.last.event === 'completed') {
    // Completed, but the review's content could not be read back.
    lines.push('issue counts unavailable')
  }

  const label = EVENT_LABELS[run.last.event] || run.last.event
  const attempts = `${run.attempts} attempt${run.attempts === 1 ? '' : 's'}`
  // Whole-seconds, and never negative if two events share a timestamp.
  const elapsedSec = Math.max(
    0,
    Math.round(
      (new Date(run.last.created_at).getTime() - new Date(run.first.created_at).getTime()) / 1000,
    ),
  )
  lines.push(`${label} · ${attempts} · took ${formatDuration(elapsedSec)}`)

  if (run.last.reason) {
    lines.push(REASON_LABELS[run.last.reason] || run.last.reason)
  }

  return lines.join('\n')
}

/**
 * Render a run's posting outcome.
 *
 * The recorders pack the GitHub review event (APPROVE / REQUEST_CHANGES /
 * COMMENT) into the head of `detail`, followed by the free-text explanation.
 */
function PostedCell({ verdict }: { verdict: ReviewLogEvent | null }) {
  if (!verdict) return <span className="mx-review-logs__posted-none">—</span>

  const [head, ...rest] = (verdict.detail || '').split(' — ')
  const explanation = rest.join(' — ')
  const posted = verdict.event === 'verdict_posted'
  const label = posted
    ? head || 'posted'
    : REASON_LABELS[verdict.reason || ''] || verdict.reason || 'not posted'

  return (
    <div className="mx-review-logs__posted">
      <Badge variant={posted ? 'success' : 'warning'}>
        {posted ? '✓' : '✗'} {label}
      </Badge>
      {posted && verdict.auto_started ? (
        <span className="mx-review-logs__posted-by" title="Posted automatically">🤖</span>
      ) : null}
      {(posted ? explanation : verdict.detail) && (
        <span className="mx-review-logs__posted-detail">
          {posted ? explanation : verdict.detail}
        </span>
      )}
    </div>
  )
}

const RUNNING_POLL_MS = 10_000

function elapsedSince(startedAtIso: string): string {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(startedAtIso).getTime()) / 1000))
  return formatDuration(seconds)
}

/** Live strip of reviews running right now, from the in-memory registry.
 * Polls while the tab is mounted so a dispatched or finished review shows up
 * without a manual refresh. */
function RunningReviewsStrip() {
  const [running, setRunning] = useState<Review[]>([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const resp = await fetchActiveReviews()
        if (!cancelled) {
          setRunning(resp.reviews.filter((r) => r.status === 'running'))
          setLoaded(true)
        }
      } catch {
        // Transient poll failure: keep showing the last known state.
      }
    }
    poll()
    const timer = setInterval(poll, RUNNING_POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  return (
    <div className="mx-review-logs__running">
      <span className="mx-review-logs__running-title">
        {running.length > 0 ? '▶' : '⏸'} Running now
        {loaded && <span className="mx-review-logs__running-count">{running.length}</span>}
      </span>
      {!loaded ? (
        <span className="mx-review-logs__running-empty">checking…</span>
      ) : running.length === 0 ? (
        <span className="mx-review-logs__running-empty">no reviews are running right now</span>
      ) : (
        <div className="mx-review-logs__running-rows">
          {running.map((r) => (
            <span key={r.key} className="mx-review-logs__running-row">
              <a href={r.pr_url || `https://github.com/${r.owner}/${r.repo}/pull/${r.pr_number}`}
                 target="_blank" rel="noreferrer">
                {r.owner}/{r.repo}#{r.pr_number}
              </a>
              <Badge size="sm" variant="info">{r.reviewer_type ?? 'default'}</Badge>
              {r.is_followup && <Badge size="sm" variant="neutral">follow-up</Badge>}
              {r.auto_started && <Badge size="sm" variant="neutral">auto</Badge>}
              <span className="mx-review-logs__running-meta">
                attempt {r.attempt ?? 1}{r.max_attempts ? `/${r.max_attempts}` : ''}
                {r.started_at ? ` · running ${elapsedSince(r.started_at)}` : ''}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export function ReviewLogsView() {
  const { selectedRepo } = useAccountStore()
  const [allRepos, setAllRepos] = useState(false)
  const [eventFilter, setEventFilter] = useState('')
  const [events, setEvents] = useState<ReviewLogEvent[]>([])
  const [stats, setStats] = useState<ReviewLogStats | null>(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  // null = the newest day with runs; a key can name a day with none (calendar).
  const [selectedDayKey, setSelectedDayKey] = useState<string | null>(null)
  const dateInputRef = useRef<HTMLInputElement>(null)

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
        fetchReviewLogs({ repo: repoScope, event: eventFilter || undefined, limit: 1000 }),
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
    // A new scope has a different day list, so snap back to its newest day.
    setSelectedDayKey(null)
    load()
  }, [repoScope, eventFilter])

  const runs = useMemo(() => groupIntoRuns(events), [events])
  const days = useMemo(() => groupIntoDays(runs), [runs])
  // The API caps the page; anything past it lands in the oldest day shown.
  const truncated = events.length < total

  const dayKeys = useMemo(() => days.map((d) => d.key), [days])
  const currentKey = selectedDayKey ?? dayKeys[0] ?? null
  const selectedGroup = days.find((d) => d.key === currentKey) ?? null
  const { older, newer } = navTargets(dayKeys, selectedDayKey)

  /**
   * Fetch the next page of older events and jump to the first day it exposes.
   *
   * Offset paging over a newest-first list overlaps when events arrive between
   * fetches (everything shifts down), so the merge dedupes by event id.
   */
  const loadOlder = async () => {
    try {
      setLoadingOlder(true)
      setError(null)
      const logs = await fetchReviewLogs({
        repo: repoScope,
        event: eventFilter || undefined,
        limit: 1000,
        offset: events.length,
      })
      const seen = new Set(events.map((e) => e.id))
      const merged = [...events, ...logs.events.filter((e) => !seen.has(e.id))]
      setEvents(merged)
      setTotal(logs.total)
      const mergedDays = groupIntoDays(groupIntoRuns(merged))
      const next = mergedDays.map((d) => d.key).find((k) => currentKey === null || k < currentKey)
      if (next) setSelectedDayKey(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load older review logs')
    } finally {
      setLoadingOlder(false)
    }
  }

  const goOlder = () => {
    if (older) setSelectedDayKey(older)
    else if (truncated) loadOlder()
  }

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

      <RunningReviewsStrip />

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

      {!loading && runs.length > 0 && currentKey && (
        <div className="mx-review-logs__daynav">
          <Button
            onClick={goOlder}
            disabled={loadingOlder || (!older && !truncated)}
            title={!older && truncated ? 'Load older days' : 'Previous day'}
          >
            ◀
          </Button>
          <span className="mx-review-logs__daynav-label">
            {formatDayLabel(currentKey)}
            {' · '}
            {selectedGroup ? selectedGroup.stats.runs : 0} run
            {selectedGroup?.stats.runs === 1 ? '' : 's'}
            {loadingOlder && <span className="mx-review-logs__daynav-loading"> · loading…</span>}
          </span>
          <Button
            onClick={() => newer && setSelectedDayKey(newer)}
            disabled={!newer}
            title="Next day"
          >
            ▶
          </Button>
          <span className="mx-review-logs__daynav-picker">
            <Button onClick={() => dateInputRef.current?.showPicker()} title="Jump to date">
              📅
            </Button>
            <input
              ref={dateInputRef}
              type="date"
              className="mx-review-logs__daynav-date"
              value={currentKey}
              min={dayKeys[dayKeys.length - 1]}
              max={dayKeys[0]}
              onChange={(e) => setSelectedDayKey(e.target.value || null)}
              tabIndex={-1}
              aria-hidden="true"
            />
          </span>
        </div>
      )}

      {!loading && runs.length > 0 && !selectedGroup && currentKey && (
        <div className="mx-empty-state">
          <h2>No review activity on {formatDayLabel(currentKey)}</h2>
          <p>Use the arrows or the calendar to jump to a day with runs.</p>
        </div>
      )}

      {!loading && selectedGroup && (
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
                <th>Posted</th>
              </tr>
            </thead>
            <tbody>
              <DayRow
                group={selectedGroup}
                partial={truncated && selectedGroup.key === days[days.length - 1].key}
              />
              {selectedGroup.runs.map((run) => (
                <Fragment key={run.runId}>
                  <tr
                    className="mx-review-logs__run"
                    onClick={() => toggle(run.runId)}
                    data-tooltip={runTooltip(run)}
                  >
                    <td>{expanded[run.runId] ? '▾' : '▸'}</td>
                    <td>#{run.prNumber}</td>
                    <td>{run.repo}</td>
                    <td>
                      <span title={formatFullDateTime(run.first.created_at)}>
                        {formatClockTime(run.first.created_at)}
                      </span>
                    </td>
                    <td>
                      <span title={formatFullDateTime(run.last.created_at)}>
                        {formatClockTime(run.last.created_at)}
                      </span>
                    </td>
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
                    <td>
                      <PostedCell verdict={run.verdict} />
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
                        <td colSpan={2}>
                          <span title={formatFullDateTime(event.created_at)}>
                            {formatClockTime(event.created_at)}
                          </span>
                        </td>
                        <td>{event.attempt ?? '—'}</td>
                        <td className="mx-review-logs__detail" colSpan={2}>
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
            {selectedGroup.stats.runs} run{selectedGroup.stats.runs === 1 ? '' : 's'} shown ·{' '}
            {runs.length} loaded across {total} event{total === 1 ? '' : 's'}
          </p>
        </>
      )}
    </div>
  )
}
