import { useEffect, useMemo } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { useAnalyticsStore } from '../../stores/useAnalyticsStore'
import { useAccountStore } from '../../stores/useAccountStore'
import { useUIStore } from '../../stores/useUIStore'
import { fetchCodeActivity, fetchContributorTimeSeries } from '../../api/analytics'
import { BarChart as CssBarChart } from './BarChart'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'
import { InfoTooltip } from '../common/InfoTooltip'
import { formatNumber } from '../../utils/formatters'

const TOP5_COLORS = ['#00d4aa', '#ff6b6b', '#4ecdc4', '#ffe66d', '#a29bfe']

export function ActivityView() {
  const selectedRepo = useAccountStore((state) => state.selectedRepo)
  const darkMode = useUIStore((state) => state.darkMode)
  const {
    codeActivity,
    activityLoading,
    activityError,
    activityTimeframe,
    setCodeActivity,
    setActivityLoading,
    setActivityError,
    setActivityTimeframe,
    contributorTimeSeries,
    setContributorTimeSeries,
    setContributorTSLoading,
    setContributorTSError,
  } = useAnalyticsStore()

  useEffect(() => {
    if (selectedRepo) {
      loadActivity()
      if (contributorTimeSeries.length === 0) {
        loadContributorData()
      }
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

  const loadContributorData = async () => {
    if (!selectedRepo) return
    try {
      setContributorTSLoading(true)
      setContributorTSError(null)
      const response = await fetchContributorTimeSeries(
        selectedRepo.owner.login,
        selectedRepo.name
      )
      setContributorTimeSeries(response.contributors)
    } catch {
      // Non-critical: top 5 chart just won't render
    } finally {
      setContributorTSLoading(false)
    }
  }

  const top5ChartData = useMemo(() => {
    if (!contributorTimeSeries.length) return []
    const top5 = contributorTimeSeries.slice(0, 5)
    const allWeeks = top5[0]?.weeks || []
    const trimmedWeeks = allWeeks.slice(-activityTimeframe)
    return trimmedWeeks.map((w) => {
      const row: Record<string, string | number> = { week: w.week }
      for (const c of top5) {
        const match = c.weeks.find((cw) => cw.week === w.week)
        row[c.login] = match ? match.commits : 0
      }
      return row
    })
  }, [contributorTimeSeries, activityTimeframe])

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
        <CssBarChart
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

        {top5ChartData.length > 0 && (() => {
          const textColor = darkMode ? '#b0b0b0' : '#666666'
          const gridColor = darkMode ? '#333333' : '#e0e0e0'
          const top5 = contributorTimeSeries.slice(0, 5)
          const formatWeek = (w: string) => { const p = w.split('-'); return `${p[1]}/${p[2]}` }
          return (
            <div className="mx-activity__chart mx-activity__chart--wide">
              <h3>Top 5 Contributors<InfoTooltip text="Weekly commit counts for the top 5 contributors by total commits. Click a legend entry to toggle visibility." /></h3>
              <ResponsiveContainer width="100%" height={250}>
                <LineChart data={top5ChartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
                  <XAxis dataKey="week" tickFormatter={formatWeek} stroke={textColor} fontSize={12} tick={{ fill: textColor }} />
                  <YAxis stroke={textColor} fontSize={12} tick={{ fill: textColor }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: darkMode ? '#1a1a2e' : '#ffffff',
                      border: `1px solid ${gridColor}`,
                      borderRadius: 8,
                      color: darkMode ? '#e0e0e0' : '#333333',
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {top5.map((c, i) => (
                    <Line key={c.login} type="monotone" dataKey={c.login} stroke={TOP5_COLORS[i]} strokeWidth={2} dot={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )
        })()}
      </div>
    </div>
  )
}
