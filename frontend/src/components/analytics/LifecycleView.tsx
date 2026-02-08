import { useEffect } from 'react'
import { useAnalyticsStore } from '../../stores/useAnalyticsStore'
import { useAccountStore } from '../../stores/useAccountStore'
import { fetchLifecycleMetrics } from '../../api/analytics'
import { SortableTable, Column } from '../common/SortableTable'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'
import { InfoTooltip } from '../common/InfoTooltip'
import { formatHours } from '../../utils/formatters'

export function LifecycleView() {
  const selectedRepo = useAccountStore((state) => state.selectedRepo)
  const {
    lifecycleMetrics,
    lifecycleLoading,
    lifecycleError,
    lifecycleSortBy,
    lifecycleSortDirection,
    setLifecycleMetrics,
    setLifecycleLoading,
    setLifecycleError,
    sortLifecycle,
    getSortedLifecyclePRs,
  } = useAnalyticsStore()

  useEffect(() => {
    if (selectedRepo) {
      loadLifecycle()
    }
  }, [selectedRepo])

  const loadLifecycle = async () => {
    if (!selectedRepo) return

    try {
      setLifecycleLoading(true)
      setLifecycleError(null)
      const response = await fetchLifecycleMetrics(
        selectedRepo.owner.login,
        selectedRepo.name
      )
      setLifecycleMetrics(response)
    } catch (err) {
      setLifecycleError(err instanceof Error ? err.message : 'Failed to load lifecycle metrics')
    } finally {
      setLifecycleLoading(false)
    }
  }

  if (lifecycleLoading) {
    return (
      <div className="mx-analytics__loading">
        <Spinner size="lg" />
        <p>Loading lifecycle metrics...</p>
      </div>
    )
  }

  if (lifecycleError) {
    return <Alert variant="error">{lifecycleError}</Alert>
  }

  if (!lifecycleMetrics) return null

  const sortedPRs = getSortedLifecyclePRs()

  const columns: Column<any>[] = [
    { key: 'number', label: 'PR#', sortable: true },
    { key: 'author', label: 'Author', sortable: true },
    { key: 'state', label: 'State', sortable: true },
    {
      key: 'time_to_first_review_hours',
      label: 'Time to Review',
      sortable: true,
      tooltip: 'Time from PR creation to first review',
      render: (pr) => formatHours(pr.time_to_first_review_hours),
    },
    {
      key: 'time_to_merge_hours',
      label: 'Time to Merge',
      sortable: true,
      tooltip: 'Time from PR creation to merge',
      render: (pr) => formatHours(pr.time_to_merge_hours),
    },
    { key: 'first_reviewer', label: 'First Reviewer', sortable: true },
  ]

  return (
    <div className="mx-lifecycle-view">
      <div className="mx-stat-cards">
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Median Time to Merge</span>
          <span className="mx-stat-card__value">
            {formatHours(lifecycleMetrics.median_time_to_merge)}
          </span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Avg Time to Merge</span>
          <span className="mx-stat-card__value">
            {formatHours(lifecycleMetrics.avg_time_to_merge)}
          </span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Median Time to First Review</span>
          <span className="mx-stat-card__value">
            {formatHours(lifecycleMetrics.median_time_to_first_review)}
          </span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Avg Time to First Review</span>
          <span className="mx-stat-card__value">
            {formatHours(lifecycleMetrics.avg_time_to_first_review)}
          </span>
        </div>
      </div>

      <div className="mx-lifecycle__distribution">
        <h3>Merge Time Distribution<InfoTooltip text="Shows how long merged PRs took from creation to merge, grouped into time buckets. Wider bars indicate more PRs fell into that time range." /></h3>
        <div className="mx-distribution-bars">
          {(() => {
            const maxCount = Math.max(...Object.values(lifecycleMetrics.distribution).map(Number))
            return Object.entries(lifecycleMetrics.distribution).map(([bucket, count]) => (
              <div key={bucket} className="mx-distribution-bar">
                <span className="mx-distribution-bar__label">{bucket}</span>
                <div className="mx-distribution-bar__track">
                  <div
                    className="mx-distribution-bar__fill"
                    style={{
                      width: `${maxCount > 0 ? (Number(count) / maxCount) * 100 : 0}%`,
                    }}
                  />
                </div>
                <span className="mx-distribution-bar__count">{count}</span>
              </div>
            ))
          })()}
        </div>
      </div>

      {lifecycleMetrics.stale_prs.length > 0 && (
        <Alert variant="warning">
          <strong>{lifecycleMetrics.stale_count} stale PRs</strong> (no activity in 14+ days)
        </Alert>
      )}

      <h3>PR Lifecycle Details</h3>
      <SortableTable
        columns={columns}
        data={sortedPRs}
        sortBy={lifecycleSortBy}
        sortDirection={lifecycleSortDirection}
        onSort={sortLifecycle}
        keyExtractor={(pr) => pr.number}
      />
    </div>
  )
}
