import { useMemo, useState } from 'react'
import { useAnalyticsStore } from '../../stores/useAnalyticsStore'
import { SortableTable, Column } from '../common/SortableTable'
import { ChipGroup } from './ChipGroup'
import { TimeSeriesChart } from './TimeSeriesChart'
import { formatNumber, formatPercentage, formatHours } from '../../utils/formatters'
import {
  StatsRow,
  toStatsRows,
  teamStatsRow,
  sortStatsRows,
  buildSeriesSpecs,
  metricSeries,
  toChartRows,
  METRIC_OPTIONS,
  HOURS_METRICS,
  RATIO_METRICS,
  TEAM_ID,
  MAX_SERIES,
} from '../../utils/analyticsSeries'

/** One-decimal plain formatter for ratio metrics (e.g. avg review rounds) --
 * no K/M suffix, no hours conversion. */
function formatRatio(value: number): string {
  return value.toFixed(1)
}

export function StatsView() {
  const daily = useAnalyticsStore((state) => state.daily)
  const base = useAnalyticsStore((state) => state.base)
  const statsView = useAnalyticsStore((state) => state.statsView)
  const setStatsView = useAnalyticsStore((state) => state.setStatsView)
  const statsSortBy = useAnalyticsStore((state) => state.statsSortBy)
  const statsSortDirection = useAnalyticsStore((state) => state.statsSortDirection)
  const sortStats = useAnalyticsStore((state) => state.sortStats)
  const statsYMode = useAnalyticsStore((state) => state.statsYMode)
  const setStatsYMode = useAnalyticsStore((state) => state.setStatsYMode)
  const statsMetrics = useAnalyticsStore((state) => state.statsMetrics)
  const toggleStatsMetric = useAnalyticsStore((state) => state.toggleStatsMetric)
  const statsPeople = useAnalyticsStore((state) => state.statsPeople)
  const toggleStatsPerson = useAnalyticsStore((state) => state.toggleStatsPerson)

  const [hidden, setHidden] = useState<Set<string>>(new Set())

  const rows = useMemo(
    () => (daily ? sortStatsRows(toStatsRows(daily.people), statsSortBy, statsSortDirection) : []),
    [daily, statsSortBy, statsSortDirection]
  )

  const specs = useMemo(
    () => (daily ? buildSeriesSpecs(statsPeople, statsMetrics) : []),
    [daily, statsPeople, statsMetrics]
  )

  if (!daily) return null

  const columns: Column<StatsRow>[] = [
    {
      key: 'login',
      label: 'Developer',
      sortable: true,
      tooltip: 'GitHub username of the contributor',
      render: (row) => (
        <div className="mx-stats-developer">
          {row.id !== TEAM_ID && (
            row.avatar_url ? (
              <img className="mx-stats-avatar" src={row.avatar_url} alt={row.login} />
            ) : (
              <span className="mx-stats-avatar mx-stats-avatar--none" />
            )
          )}
          <span>{row.login}</span>
        </div>
      ),
    },
    {
      key: 'prs_created',
      label: 'PRs',
      sortable: true,
      tooltip: 'PRs created targeting the selected base, in this window',
      render: (row) => formatNumber(row.prs_created),
    },
    {
      key: 'prs_merged',
      label: 'Merged',
      sortable: true,
      tooltip: 'Number of merged PRs',
      render: (row) => formatNumber(row.prs_merged),
    },
    {
      key: 'prs_closed',
      label: 'Closed',
      sortable: true,
      tooltip: 'Number of closed (not merged) PRs',
      render: (row) => formatNumber(row.prs_closed),
    },
    {
      key: 'merge_rate',
      label: 'Merge %',
      sortable: true,
      tooltip: 'Merged ÷ (merged + closed) in the window',
      render: (row) => (
        <span className="mx-stats-merge-rate">
          {row.merge_rate === null ? 'N/A' : formatPercentage(row.merge_rate)}
        </span>
      ),
    },
    {
      key: 'reviews',
      label: 'Reviews',
      sortable: true,
      tooltip: 'Total reviews given',
      render: (row) => formatNumber(row.reviews),
    },
    {
      key: 'approvals',
      label: 'Approvals',
      sortable: true,
      tooltip: 'Number of approval reviews',
      render: (row) => formatNumber(row.approvals),
    },
    {
      key: 'changes_requested',
      label: 'Changes Req.',
      sortable: true,
      tooltip: 'Number of "changes requested" reviews',
      render: (row) => formatNumber(row.changes_requested),
    },
    {
      key: 'additions',
      label: 'Lines +',
      sortable: true,
      tooltip: 'Total lines added',
      render: (row) => <span className="mx-stats-additions">{formatNumber(row.additions)}</span>,
    },
    {
      key: 'deletions',
      label: 'Lines -',
      sortable: true,
      tooltip: 'Total lines deleted',
      render: (row) => <span className="mx-stats-deletions">{formatNumber(row.deletions)}</span>,
    },
    {
      key: 'commits',
      label: 'Commits',
      sortable: true,
      tooltip: 'Total commits',
      render: (row) => formatNumber(row.commits),
    },
    {
      key: 'avg_merge_hours',
      label: 'Avg merge',
      sortable: true,
      tooltip: 'Average time from PR open to merge',
      render: (row) => formatHours(row.avg_merge_hours),
    },
    {
      key: 'avg_review_rounds',
      label: 'Avg rounds',
      sortable: true,
      tooltip: 'Average completed review-pipeline runs per merged PR (only PRs that went through the pipeline)',
      render: (row) => (row.avg_review_rounds === null ? 'N/A' : row.avg_review_rounds.toFixed(1)),
    },
  ]

  const atCap = statsPeople.length * statsMetrics.length >= MAX_SERIES

  const personOptions = [
    { value: TEAM_ID, label: 'Team' },
    ...[...daily.people]
      .sort((a, b) => b.totals.commits - a.totals.commits)
      .map((p) => ({ value: p.login, label: p.login })),
  ].map((o) => ({
    ...o,
    swatch: specs.find((s) => s.personId === o.value)?.color,
    disabled: atCap && !statsPeople.includes(o.value),
  }))

  const metricOptions = METRIC_OPTIONS.map((o) => ({
    ...o,
    disabled: atCap && !statsMetrics.includes(o.value),
  }))

  const personMap = new Map(daily.people.map((p) => [p.login, p]))
  const validSpecs = specs.filter((s) => s.personId === TEAM_ID || personMap.has(s.personId))
  const columnsForChart: Record<string, (number | null)[]> = {}
  for (const spec of validSpecs) {
    const src = spec.personId === TEAM_ID ? daily.team.series : personMap.get(spec.personId)!.series
    columnsForChart[spec.id] = metricSeries(src, spec.metric, statsYMode)
  }
  const chartRows = toChartRows(daily.days, columnsForChart)
  const allHours = statsMetrics.every((m) => HOURS_METRICS.has(m))
  const someHours = statsMetrics.some((m) => HOURS_METRICS.has(m))
  const allRatio = statsMetrics.every((m) => RATIO_METRICS.has(m))
  const someRatio = statsMetrics.some((m) => RATIO_METRICS.has(m))
  const yFormatter = allHours ? formatHours : allRatio ? formatRatio : formatNumber
  const mixedUnitHints = [
    someHours && !allHours ? 'avg merge time is in hours' : null,
    someRatio && !allRatio ? 'avg review rounds is a decimal count' : null,
  ].filter((hint): hint is string => hint !== null)

  return (
    <div className="mx-stats-view">
      <div className="mx-activity__controls">
        <ChipGroup
          options={[
            { value: 'table' as const, label: 'Table' },
            { value: 'series' as const, label: 'Time series' },
          ]}
          selected={[statsView]}
          onToggle={setStatsView}
        />
      </div>

      {statsView === 'table' && (
        <>
          <SortableTable
            columns={columns}
            data={rows}
            sortBy={statsSortBy}
            sortDirection={statsSortDirection}
            onSort={sortStats}
            keyExtractor={(row) => row.id}
            className="mx-stats-table"
            footerRow={teamStatsRow(daily.team)}
          />
          {rows.length === 0 && (
            <p className="mx-analytics__hint">No PRs targeting {base} in this window</p>
          )}
        </>
      )}

      {statsView === 'series' && (
        <>
          <div className="mx-activity__controls">
            <ChipGroup
              options={[
                { value: 'daily' as const, label: 'Per-day' },
                { value: 'cumulative' as const, label: 'Cumulative' },
              ]}
              selected={[statsYMode]}
              onToggle={setStatsYMode}
            />
          </div>
          <div className="mx-activity__controls">
            <ChipGroup options={metricOptions} selected={statsMetrics} onToggle={toggleStatsMetric} />
          </div>
          <div className="mx-activity__controls">
            <ChipGroup options={personOptions} selected={statsPeople} onToggle={toggleStatsPerson} />
          </div>
          {atCap && <p className="mx-analytics__hint">Up to 16 series at once</p>}
          {mixedUnitHints.length > 0 && (
            <p className="mx-analytics__hint">{mixedUnitHints.join('; ')}</p>
          )}
          <TimeSeriesChart
            rows={chartRows}
            series={validSpecs}
            hidden={hidden}
            onToggle={(id) =>
              setHidden((prev) => {
                const next = new Set(prev)
                if (next.has(id)) next.delete(id)
                else next.add(id)
                return next
              })
            }
            height={400}
            yFormatter={yFormatter}
          />
        </>
      )}
    </div>
  )
}
