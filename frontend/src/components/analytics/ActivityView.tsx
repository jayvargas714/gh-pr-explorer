import { useMemo, useState } from 'react'
import { useAnalyticsStore } from '../../stores/useAnalyticsStore'
import { useChartTheme } from './chartTheme'
import { DailyBarChart } from './DailyBarChart'
import { TimeSeriesChart } from './TimeSeriesChart'
import { InfoTooltip } from '../common/InfoTooltip'
import { formatNumber } from '../../utils/formatters'
import { summarizeTeam, toChartRows, seriesColor } from '../../utils/analyticsSeries'

const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// Formats a 'YYYY-MM-DD' day string without going through Date/toLocaleDateString,
// which would shift the day backward in timezones behind UTC.
function formatPeakDay(day: string): string {
  const [year, month, date] = day.split('-').map(Number)
  return `${MONTH_ABBR[month - 1]} ${date}, ${year}`
}

export function ActivityView() {
  const daily = useAnalyticsStore((state) => state.daily)
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const theme = useChartTheme()

  const summary = useMemo(
    () => (daily ? summarizeTeam(daily.days, daily.team.series) : null),
    [daily]
  )

  const rows = useMemo(
    () =>
      daily
        ? toChartRows(daily.days, {
            commits: daily.team.series.commits,
            additions: daily.team.series.additions,
            deletions: daily.team.series.deletions,
            prs_created: daily.team.series.prs_created,
            prs_merged: daily.team.series.prs_merged,
            prs_closed: daily.team.series.prs_closed,
          })
        : [],
    [daily]
  )

  if (!daily || !summary) return null

  const prSeries = [
    { id: 'prs_created', label: 'PRs created', color: seriesColor(0), personId: '', metric: 'prs_created' as const },
    { id: 'prs_merged', label: 'merges', color: seriesColor(1), personId: '', metric: 'prs_merged' as const },
    { id: 'prs_closed', label: 'closed', color: seriesColor(2), personId: '', metric: 'prs_closed' as const },
  ]

  return (
    <div className="mx-activity-view">
      <div className="mx-stat-cards">
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Total Commits</span>
          <span className="mx-stat-card__value">{formatNumber(summary.totalCommits)}</span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Avg Commits/Day</span>
          <span className="mx-stat-card__value">{summary.avgCommitsPerDay.toFixed(1)}</span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Lines Added</span>
          <span className="mx-stat-card__value mx-stats-additions">+{formatNumber(summary.additions)}</span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Lines Deleted</span>
          <span className="mx-stat-card__value mx-stats-deletions">-{formatNumber(summary.deletions)}</span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Peak Day</span>
          <span className="mx-stat-card__value">
            {summary.peakDay ? formatPeakDay(summary.peakDay) : 'N/A'}
          </span>
          {summary.peakDay && <span className="mx-stat-card__sub">{summary.peakCommits} commits</span>}
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">PRs Merged</span>
          <span className="mx-stat-card__value">{formatNumber(summary.prsMerged)}</span>
        </div>
      </div>

      <div className="mx-activity__charts">
        <div className="mx-activity__chart">
          <h3>Commits per day</h3>
          <DailyBarChart rows={rows} bars={[{ id: 'commits', label: 'Commits', color: theme.primary }]} />
        </div>

        <div className="mx-activity__chart">
          <h3>
            Lines added vs deleted
            <InfoTooltip text="From PRs merged into the selected base, attributed on merge day" />
          </h3>
          <DailyBarChart
            rows={rows}
            bars={[
              { id: 'additions', label: 'Lines added', color: theme.success, stackId: 'lines' },
              { id: 'deletions', label: 'Lines deleted', color: theme.error, stackId: 'lines' },
            ]}
          />
        </div>

        <div className="mx-activity__chart mx-activity__chart--wide">
          <h3>PRs created / merged / closed</h3>
          <TimeSeriesChart
            rows={rows}
            series={prSeries}
            hidden={hidden}
            onToggle={(id) =>
              setHidden((prev) => {
                const next = new Set(prev)
                if (next.has(id)) next.delete(id)
                else next.add(id)
                return next
              })
            }
          />
        </div>
      </div>
    </div>
  )
}
