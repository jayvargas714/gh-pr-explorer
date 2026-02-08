import { formatDuration, formatNumber, formatPercentage } from '../../utils/formatters'

interface WorkflowStatsProps {
  stats: {
    total_runs: number
    pass_rate: number
    avg_duration: number
    failure_count: number
  }
}

export function WorkflowStats({ stats }: WorkflowStatsProps) {
  return (
    <div className="mx-stat-cards">
      <div className="mx-stat-card">
        <span className="mx-stat-card__label">Total Runs</span>
        <span className="mx-stat-card__value">{formatNumber(stats.total_runs)}</span>
      </div>

      <div className="mx-stat-card">
        <span className="mx-stat-card__label">Pass Rate</span>
        <span className="mx-stat-card__value">{formatPercentage(stats.pass_rate)}</span>
      </div>

      <div className="mx-stat-card">
        <span className="mx-stat-card__label">Avg Duration</span>
        <span className="mx-stat-card__value">{formatDuration(stats.avg_duration)}</span>
      </div>

      <div className="mx-stat-card">
        <span className="mx-stat-card__label">Failures</span>
        <span className="mx-stat-card__value mx-stats-deletions">
          {formatNumber(stats.failure_count)}
        </span>
      </div>
    </div>
  )
}
