import { useMemo, useState } from 'react'
import { useAnalyticsStore } from '../../stores/useAnalyticsStore'
import { ChipGroup } from './ChipGroup'
import { TimeSeriesChart } from './TimeSeriesChart'
import { MAX_SERIES, seriesColor, toChartRows } from '../../utils/analyticsSeries'

const METRIC_OPTIONS = [
  { value: 'commits' as const, label: 'Commits' },
  { value: 'additions' as const, label: 'Lines added' },
  { value: 'deletions' as const, label: 'Lines deleted' },
  { value: 'prs_merged' as const, label: 'Merges' },
  { value: 'reviews' as const, label: 'Reviews' },
]

export function ContributorsView() {
  const daily = useAnalyticsStore((state) => state.daily)
  const contribMetric = useAnalyticsStore((state) => state.contribMetric)
  const setContribMetric = useAnalyticsStore((state) => state.setContribMetric)
  const [hidden, setHidden] = useState<Set<string>>(new Set())

  const allPeople = useMemo(
    () => (daily ? [...daily.people].sort((a, b) => b.totals[contribMetric] - a.totals[contribMetric]) : []),
    [daily, contribMetric]
  )

  const people = useMemo(() => allPeople.slice(0, MAX_SERIES), [allPeople])

  const specs = useMemo(
    () => people.map((p, i) => ({ id: p.login, label: p.login, color: seriesColor(i), personId: p.login, metric: contribMetric })),
    [people, contribMetric]
  )

  const rows = useMemo(
    () => (daily ? toChartRows(daily.days, Object.fromEntries(people.map((p) => [p.login, p.series[contribMetric]]))) : []),
    [daily, people, contribMetric]
  )

  if (!daily) return null

  const metricLabel = METRIC_OPTIONS.find((m) => m.value === contribMetric)?.label ?? contribMetric

  return (
    <div className="mx-contributors-view">
      <div className="mx-activity__controls">
        <ChipGroup options={METRIC_OPTIONS} selected={[contribMetric]} onToggle={setContribMetric} />
      </div>

      {allPeople.length === 0 ? (
        <p className="mx-analytics__hint">No contributors in this window</p>
      ) : (
        <>
          {allPeople.length > MAX_SERIES && (
            <p className="mx-analytics__hint">
              Showing top {MAX_SERIES} of {allPeople.length} contributors by {metricLabel}
            </p>
          )}
          <div className="mx-activity__controls">
            <button type="button" className="mx-button-group__item" onClick={() => setHidden(new Set())}>
              Show all
            </button>
            <button
              type="button"
              className="mx-button-group__item"
              onClick={() => setHidden(new Set(specs.map((s) => s.id)))}
            >
              Hide all
            </button>
          </div>
          <div className="mx-contributors__chart">
            <TimeSeriesChart
              rows={rows}
              series={specs}
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
            />
          </div>
        </>
      )}
    </div>
  )
}
