import { useEffect, useState, useMemo } from 'react'
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
import { fetchContributorTimeSeries } from '../../api/analytics'
import { CacheTimestamp } from '../common/CacheTimestamp'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'

const COLORS = [
  '#00d4aa', '#ff6b6b', '#4ecdc4', '#ffe66d', '#a29bfe',
  '#fd79a8', '#fdcb6e', '#6c5ce7', '#00b894', '#e17055',
]

export function ContributorsView() {
  const selectedRepo = useAccountStore((state) => state.selectedRepo)
  const darkMode = useUIStore((state) => state.darkMode)
  const {
    contributorTimeSeries,
    contributorTSLoading,
    contributorTSError,
    contributorTSTimeframe,
    contributorTSMetric,
    cacheMeta,
    setContributorTimeSeries,
    setContributorTSLoading,
    setContributorTSError,
    setContributorTSTimeframe,
    setContributorTSMetric,
    setCacheMeta,
  } = useAnalyticsStore()

  const [hiddenContributors, setHiddenContributors] = useState<Set<string>>(new Set())

  useEffect(() => {
    if (selectedRepo && contributorTimeSeries.length === 0) {
      loadData()
    }
  }, [selectedRepo])

  const loadData = async () => {
    if (!selectedRepo) return
    try {
      setContributorTSLoading(true)
      setContributorTSError(null)
      const response = await fetchContributorTimeSeries(
        selectedRepo.owner.login,
        selectedRepo.name
      )
      setContributorTimeSeries(response.contributors)
      setCacheMeta('contributors', response)
    } catch (err) {
      setContributorTSError(err instanceof Error ? err.message : 'Failed to load contributor data')
    } finally {
      setContributorTSLoading(false)
    }
  }

  const timeframeOptions = [
    { value: 4, label: '1M' },
    { value: 13, label: '3M' },
    { value: 26, label: '6M' },
    { value: 52, label: '1Y' },
  ]

  const metricOptions: { value: 'commits' | 'additions' | 'deletions'; label: string }[] = [
    { value: 'commits', label: 'Commits' },
    { value: 'additions', label: 'Lines Added' },
    { value: 'deletions', label: 'Lines Deleted' },
  ]

  const chartData = useMemo(() => {
    if (!contributorTimeSeries.length) return []

    const visibleContributors = contributorTimeSeries.filter(
      (c) => !hiddenContributors.has(c.login)
    )
    if (!visibleContributors.length) return []

    // Take weeks from the first contributor (all should have same weeks)
    const allWeeks = contributorTimeSeries[0]?.weeks || []
    const trimmedWeeks = allWeeks.slice(-contributorTSTimeframe)

    return trimmedWeeks.map((w) => {
      const row: Record<string, string | number> = { week: w.week }
      for (const contributor of visibleContributors) {
        const matchingWeek = contributor.weeks.find((cw) => cw.week === w.week)
        row[contributor.login] = matchingWeek ? matchingWeek[contributorTSMetric] : 0
      }
      return row
    })
  }, [contributorTimeSeries, contributorTSTimeframe, contributorTSMetric, hiddenContributors])

  const toggleContributor = (login: string) => {
    setHiddenContributors((prev) => {
      const next = new Set(prev)
      if (next.has(login)) {
        next.delete(login)
      } else {
        next.add(login)
      }
      return next
    })
  }

  if (contributorTSLoading) {
    return (
      <div className="mx-analytics__loading">
        <Spinner size="lg" />
        <p>Loading contributor data...</p>
      </div>
    )
  }

  if (contributorTSError) {
    return <Alert variant="error">{contributorTSError}</Alert>
  }

  if (!contributorTimeSeries.length) return null

  const textColor = darkMode ? '#b0b0b0' : '#666666'
  const gridColor = darkMode ? '#333333' : '#e0e0e0'

  const formatWeekLabel = (week: string) => {
    const parts = week.split('-')
    return `${parts[1]}/${parts[2]}`
  }

  const contributorsCacheMeta = cacheMeta.contributors

  return (
    <div className="mx-contributors-view">
      <CacheTimestamp
        lastUpdated={contributorsCacheMeta.lastUpdated}
        stale={contributorsCacheMeta.stale}
        refreshing={contributorsCacheMeta.refreshing}
      />
      <div className="mx-activity__controls">
        <label>Timeframe:</label>
        {timeframeOptions.map((option) => (
          <button
            key={option.value}
            className={`mx-button-group__item ${
              contributorTSTimeframe === option.value ? 'mx-button-group__item--active' : ''
            }`}
            onClick={() => setContributorTSTimeframe(option.value)}
          >
            {option.label}
          </button>
        ))}
        <span style={{ width: 16 }} />
        <label>Metric:</label>
        {metricOptions.map((option) => (
          <button
            key={option.value}
            className={`mx-button-group__item ${
              contributorTSMetric === option.value ? 'mx-button-group__item--active' : ''
            }`}
            onClick={() => setContributorTSMetric(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="mx-contributors__chart">
        <ResponsiveContainer width="100%" height={400}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
            <XAxis
              dataKey="week"
              tickFormatter={formatWeekLabel}
              stroke={textColor}
              fontSize={12}
              tick={{ fill: textColor }}
            />
            <YAxis
              stroke={textColor}
              fontSize={12}
              tick={{ fill: textColor }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: darkMode ? '#1a1a2e' : '#ffffff',
                border: `1px solid ${gridColor}`,
                borderRadius: 8,
                color: darkMode ? '#e0e0e0' : '#333333',
              }}
            />
            <Legend
              onClick={(e) => {
                if (typeof e.value === 'string') toggleContributor(e.value)
              }}
              wrapperStyle={{ cursor: 'pointer', fontSize: 12 }}
            />
            {contributorTimeSeries.map((contributor, i) => (
              <Line
                key={contributor.login}
                type="monotone"
                dataKey={contributor.login}
                stroke={COLORS[i % COLORS.length]}
                strokeWidth={2}
                dot={false}
                hide={hiddenContributors.has(contributor.login)}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
