import { formatDuration, formatNumber } from '../../utils/formatters'
import { InfoTooltip } from '../common/InfoTooltip'

interface WorkflowStatsProps {
  stats: {
    total_runs: number
    all_time_total: number
    pass_rate: number
    avg_duration: number
    failure_count: number
  }
}

export function WorkflowStats({ stats }: WorkflowStatsProps) {
  const runsLabel = stats.total_runs >= 300 ? 'Last 300 Runs' : 'Recent Runs'

  return (
    <div className="mx-stat-cards">
      <div className="mx-stat-card">
        <span className="mx-stat-card__label">
          All-Time Runs
          <InfoTooltip text="Total number of workflow runs across the entire repository history. This count comes directly from GitHub and is not limited by the fetched data." />
        </span>
        <span className="mx-stat-card__value">{formatNumber(stats.all_time_total)}</span>
      </div>

      <div className="mx-stat-card">
        <span className="mx-stat-card__label">
          {runsLabel}
          <InfoTooltip text="The most recent workflow runs fetched from GitHub (up to 300). All stats below — pass rate, avg duration, and failures — are calculated from this set only." />
        </span>
        <span className="mx-stat-card__value">{formatNumber(stats.total_runs)}</span>
      </div>

      <div className="mx-stat-card">
        <span className="mx-stat-card__label">
          Pass Rate
          <InfoTooltip text={`Percentage of completed runs that succeeded, calculated from the ${runsLabel.toLowerCase()} — not all-time.`} />
        </span>
        <span className="mx-stat-card__value">{stats.pass_rate.toFixed(1)}%</span>
      </div>

      <div className="mx-stat-card">
        <span className="mx-stat-card__label">
          Avg Duration
          <InfoTooltip text={`Average time from start to completion per run, calculated from the ${runsLabel.toLowerCase()}.`} />
        </span>
        <span className="mx-stat-card__value">{formatDuration(stats.avg_duration)}</span>
      </div>

      <div className="mx-stat-card">
        <span className="mx-stat-card__label">
          Failures
          <InfoTooltip text={`Total number of failed runs within the ${runsLabel.toLowerCase()}.`} />
        </span>
        <span className="mx-stat-card__value mx-stats-deletions">
          {formatNumber(stats.failure_count)}
        </span>
      </div>
    </div>
  )
}
