import { useEffect, useMemo, useState } from 'react'
import { PipelineStage } from '../../api/types'
import { usePipelineStore } from '../../stores/usePipelineStore'
import { useUIStore } from '../../stores/useUIStore'
import { useAutomationStore } from '../../stores/useAutomationStore'
import { Button } from '../common/Button'
import { BadgeFilterPopover } from '../swimlane/BadgeFilterPopover'
import { STAGE_META, STAGE_ORDER, summarize } from './pipelineFilters'
import { useFilteredRows } from './useFilteredRows'

interface PipelineHeaderProps {
  onClose: () => void
  onRefresh: () => void
}

/** "8s ago" / "3m ago" / "2h ago" — finer than formatRelativeTime's "just now",
 * because the point of the indicator is to show the 10 s poll ticking. */
function formatAge(iso: string | null, nowMs: number): string | null {
  if (!iso) return null
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return null
  const sec = Math.max(0, Math.floor((nowMs - t) / 1000))
  if (sec < 60) return `${sec}s ago`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  return `${Math.floor(hr / 24)}d ago`
}

export function PipelineHeader({ onClose, onRefresh }: PipelineHeaderProps) {
  const rows = usePipelineStore((s) => s.rows)
  const generatedAt = usePipelineStore((s) => s.generatedAt)
  const prDataSyncedAt = usePipelineStore((s) => s.prDataSyncedAt)
  const refreshing = usePipelineStore((s) => s.refreshing)
  const loading = usePipelineStore((s) => s.loading)
  const includeClosed = usePipelineStore((s) => s.includeClosed)
  const setIncludeClosed = usePipelineStore((s) => s.setIncludeClosed)

  const query = usePipelineStore((s) => s.query)
  const setQuery = usePipelineStore((s) => s.setQuery)
  const stages = usePipelineStore((s) => s.stages)
  const toggleStage = usePipelineStore((s) => s.toggleStage)
  const badgeFilters = usePipelineStore((s) => s.badgeFilters)
  const badgeFilterMode = usePipelineStore((s) => s.badgeFilterMode)
  const toggleBadgeFilter = usePipelineStore((s) => s.toggleBadgeFilter)
  const setBadgeFilterMode = usePipelineStore((s) => s.setBadgeFilterMode)
  const clearBadgeFilters = usePipelineStore((s) => s.clearBadgeFilters)
  const repo = usePipelineStore((s) => s.repo)
  const setRepo = usePipelineStore((s) => s.setRepo)
  const reviewerKey = usePipelineStore((s) => s.reviewerKey)
  const setReviewerKey = usePipelineStore((s) => s.setReviewerKey)
  const minRounds = usePipelineStore((s) => s.minRounds)
  const setMinRounds = usePipelineStore((s) => s.setMinRounds)
  const resetFilters = usePipelineStore((s) => s.resetFilters)

  const setActiveView = useUIStore((s) => s.setActiveView)
  const reviewers = useAutomationStore((s) => s.reviewers)

  const summary = useMemo(() => summarize(rows), [rows])
  const stageCounts = useMemo(() => {
    const counts = {} as Record<PipelineStage, number>
    for (const s of STAGE_ORDER) counts[s] = 0
    for (const r of rows) counts[r.stage] = (counts[r.stage] ?? 0) + 1
    return counts
  }, [rows])
  const repos = useMemo(() => Array.from(new Set(rows.map((r) => r.repo))).sort(), [rows])
  const reviewerKeys = useMemo(() => {
    const keys = new Set<string>()
    for (const r of rows) if (r.dispatch.reviewerKey) keys.add(r.dispatch.reviewerKey)
    return Array.from(keys).sort()
  }, [rows])
  const reviewerLabel = (key: string) => reviewers.find((r) => r.key === key)?.label ?? key

  const filteredRows = useFilteredRows()
  const filterActive =
    query.trim().length > 0 ||
    stages.size > 0 ||
    badgeFilters.size > 0 ||
    repo !== '' ||
    reviewerKey !== '' ||
    minRounds > 0

  // Tick so the freshness indicator counts up between polls.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 5_000)
    return () => window.clearInterval(timer)
  }, [])
  const snapshotAge = formatAge(generatedAt, now)
  const prDataAge = formatAge(prDataSyncedAt, now)

  const visibleStages = STAGE_ORDER.filter((s) => s !== 'closed' || includeClosed)

  return (
    <header className="mx-pipe-modal__header">
      <div className="mx-pipe-modal__title-row">
        <div className="mx-pipe-modal__title">
          <h2>🤖 Pipeline</h2>
          <span className="mx-pipe-counts" aria-label="Pipeline counts">
            <span className="mx-pipe-counts__item">{summary.total} PRs</span>
            <span className="mx-pipe-counts__item">⏳ {summary.waiting} waiting</span>
            <span className="mx-pipe-counts__item">▶ {summary.reviewing} reviewing</span>
            <span className="mx-pipe-counts__item">✓ {summary.reviewed} reviewed</span>
            <span
              className={
                'mx-pipe-counts__item' +
                (summary.attention > 0 ? ' mx-pipe-counts__item--attention' : '')
              }
              data-tooltip="Unidentified, failed, or changes requested with new commits"
            >
              ⚠ {summary.attention} attention
            </span>
          </span>
          {snapshotAge && (
            <span className={'mx-pipe-freshness' + (refreshing ? ' mx-pipe-freshness--refreshing' : '')}>
              Updated {snapshotAge}
              {prDataAge && ` · PR data ${prDataAge}`}
              {refreshing && ' · refreshing…'}
            </span>
          )}
        </div>

        <div className="mx-pipe-modal__actions">
          <label className="mx-pipe-toggle" data-tooltip="Include merged and closed PRs">
            <input
              type="checkbox"
              checked={includeClosed}
              onChange={(e) => setIncludeClosed(e.target.checked)}
            />
            Include closed
          </label>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              onClose()
              setActiveView('automation')
            }}
            data-tooltip="Automation settings"
            aria-label="Automation settings"
          >
            ⚙
          </Button>
          <Button variant="ghost" size="sm" onClick={onRefresh} disabled={loading} data-tooltip="Refresh">
            ↻
          </Button>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            ✕
          </Button>
        </div>
      </div>

      <div className="mx-pipe-modal__filters">
        <div className="mx-pipe-modal__search">
          <input
            type="search"
            className="mx-swl-search__input"
            placeholder="Search PR # or text…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setQuery('')
            }}
            aria-label="Search pipeline rows"
          />
          {query && (
            <button
              type="button"
              className="mx-swl-search__clear"
              onClick={() => setQuery('')}
              aria-label="Clear search"
            >
              ×
            </button>
          )}
        </div>

        <div className="mx-pipe-stage-chips" role="group" aria-label="Stage filter">
          {visibleStages.map((stage) => {
            const on = stages.has(stage)
            const { icon, label } = STAGE_META[stage]
            return (
              <button
                key={stage}
                type="button"
                className={
                  `mx-pipe-stage-chip mx-pipe-stage-chip--${stage}` +
                  (on ? ' mx-pipe-stage-chip--on' : '')
                }
                onClick={() => toggleStage(stage)}
                aria-pressed={on}
              >
                {icon} {label}
                <span className="mx-pipe-stage-chip__count">{stageCounts[stage] ?? 0}</span>
              </button>
            )
          })}
        </div>

        <BadgeFilterPopover
          badgeFilters={badgeFilters}
          mode={badgeFilterMode}
          onToggle={toggleBadgeFilter}
          onSetMode={setBadgeFilterMode}
          onClear={clearBadgeFilters}
          tooltip="Filter rows by badge"
        />

        <select
          className="mx-select mx-pipe-select"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          aria-label="Filter by repository"
        >
          <option value="">All repos</option>
          {repos.map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>

        <select
          className="mx-select mx-pipe-select"
          value={reviewerKey}
          onChange={(e) => setReviewerKey(e.target.value)}
          aria-label="Filter by reviewer"
        >
          <option value="">All reviewers</option>
          {reviewerKeys.map((k) => (
            <option key={k} value={k}>{reviewerLabel(k)}</option>
          ))}
        </select>

        <label className="mx-pipe-rounds">
          rounds ≥
          <input
            type="number"
            min={0}
            className="mx-pipe-rounds__input"
            value={minRounds}
            onChange={(e) => setMinRounds(Number(e.target.value))}
            aria-label="Minimum review rounds"
          />
        </label>

        {filterActive && (
          <>
            <button
              type="button"
              className="mx-swl-filter-reset"
              onClick={resetFilters}
              aria-label="Clear all filters"
            >
              Clear all
            </button>
            <span className="mx-swl-search__count" aria-live="polite">
              {filteredRows.length} match{filteredRows.length === 1 ? '' : 'es'}
            </span>
          </>
        )}
      </div>
    </header>
  )
}
