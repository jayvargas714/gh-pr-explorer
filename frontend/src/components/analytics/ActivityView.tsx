import { useEffect } from 'react'
import { useAnalyticsStore } from '../../stores/useAnalyticsStore'
import { useAccountStore } from '../../stores/useAccountStore'
import { fetchCodeActivity } from '../../api/analytics'
import { BarChart } from './BarChart'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'
import { InfoTooltip } from '../common/InfoTooltip'
import { formatNumber } from '../../utils/formatters'

export function ActivityView() {
  const selectedRepo = useAccountStore((state) => state.selectedRepo)
  const {
    codeActivity,
    activityLoading,
    activityError,
    activityTimeframe,
    setCodeActivity,
    setActivityLoading,
    setActivityError,
    setActivityTimeframe,
  } = useAnalyticsStore()

  useEffect(() => {
    if (selectedRepo) {
      loadActivity()
    }
  }, [selectedRepo, activityTimeframe])

  const loadActivity = async () => {
    if (!selectedRepo) return

    try {
      setActivityLoading(true)
      setActivityError(null)
      const response = await fetchCodeActivity(
        selectedRepo.owner.login,
        selectedRepo.name,
        activityTimeframe
      )
      setCodeActivity(response)
    } catch (err) {
      setActivityError(err instanceof Error ? err.message : 'Failed to load activity data')
    } finally {
      setActivityLoading(false)
    }
  }

  if (activityLoading) {
    return (
      <div className="mx-analytics__loading">
        <Spinner size="lg" />
        <p>Loading code activity...</p>
      </div>
    )
  }

  if (activityError) {
    return <Alert variant="error">{activityError}</Alert>
  }

  if (!codeActivity) return null

  const timeframeOptions = [
    { value: 4, label: '1 Month' },
    { value: 13, label: '3 Months' },
    { value: 26, label: '6 Months' },
    { value: 52, label: '1 Year' },
  ]

  return (
    <div className="mx-activity-view">
      <div className="mx-activity__controls">
        <label>Timeframe:</label>
        {timeframeOptions.map((option) => (
          <button
            key={option.value}
            className={`mx-button-group__item ${
              activityTimeframe === option.value ? 'mx-button-group__item--active' : ''
            }`}
            onClick={() => setActivityTimeframe(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="mx-stat-cards">
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Total Commits</span>
          <span className="mx-stat-card__value">
            {formatNumber(codeActivity.summary.total_commits)}
          </span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Avg Weekly Commits</span>
          <span className="mx-stat-card__value">
            {codeActivity.summary.avg_weekly_commits.toFixed(1)}
          </span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Lines Added</span>
          <span className="mx-stat-card__value mx-stats-additions">
            +{formatNumber(codeActivity.summary.total_additions)}
          </span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Lines Deleted</span>
          <span className="mx-stat-card__value mx-stats-deletions">
            -{formatNumber(codeActivity.summary.total_deletions)}
          </span>
        </div>
      </div>

      <div className="mx-activity__charts">
        <BarChart
          title="Weekly Commits"
          tooltip="Total number of commits pushed each week. Each bar represents one week in the selected timeframe. Hover a bar to see the exact week and count."
          data={codeActivity.weekly_commits.map((w) => ({
            label: w.week,
            value: w.total,
          }))}
          color="var(--mx-color-primary)"
        />

        {(() => {
          const maxTotal = Math.max(1, ...codeActivity.code_changes.map((c) => c.additions + c.deletions))
          return (
            <div className="mx-activity__chart">
              <h3>Code Changes<InfoTooltip text="Lines of code added (green) and deleted (red) each week. Taller bars indicate more code churn. Hover a segment to see the exact count." /></h3>
              <div className="mx-stacked-chart">
                {codeActivity.code_changes.map((change, i) => {
                  const total = change.additions + change.deletions
                  const barHeight = (total / maxTotal) * 100
                  const addPct = total > 0 ? (change.additions / total) * 100 : 50
                  return (
                    <div key={i} className="mx-stacked-bar" style={{ height: `${barHeight}%` }}>
                      <div
                        className="mx-stacked-bar__additions"
                        style={{ flex: addPct }}
                        title={`+${change.additions}`}
                      />
                      <div
                        className="mx-stacked-bar__deletions"
                        style={{ flex: 100 - addPct }}
                        title={`-${change.deletions}`}
                      />
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })()}

        {(() => {
          const maxTotal = Math.max(1, ...codeActivity.owner_commits.map((c, idx) => c + (codeActivity.community_commits[idx] || 0)))
          return (
            <div className="mx-activity__chart">
              <h3>Participation<InfoTooltip text="Compares weekly commits from the repository owner (green) versus all other contributors (purple). Helps identify how much activity comes from the primary maintainer vs the broader team." /></h3>
              <div className="mx-grouped-chart">
                {codeActivity.owner_commits.map((ownerCommits, i) => {
                  const communityCommits = codeActivity.community_commits[i] || 0
                  return (
                    <div key={i} className="mx-grouped-bar">
                      <div
                        className="mx-grouped-bar__owner"
                        style={{ height: `${(ownerCommits / maxTotal) * 100}%` }}
                        title={`Owner: ${ownerCommits}`}
                      />
                      <div
                        className="mx-grouped-bar__community"
                        style={{ height: `${(communityCommits / maxTotal) * 100}%` }}
                        title={`Contributors: ${communityCommits}`}
                      />
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })()}
      </div>
    </div>
  )
}
