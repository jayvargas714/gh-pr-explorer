import { useEffect } from 'react'
import { useAnalyticsStore } from '../../stores/useAnalyticsStore'
import { useAccountStore } from '../../stores/useAccountStore'
import { fetchReviewResponsiveness } from '../../api/analytics'
import { SortableTable, Column } from '../common/SortableTable'
import { CacheTimestamp } from '../common/CacheTimestamp'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'
import { formatHours, formatNumber } from '../../utils/formatters'

export function ResponsivenessView() {
  const selectedRepo = useAccountStore((state) => state.selectedRepo)
  const {
    reviewResponsiveness,
    responsivenessLoading,
    responsivenessError,
    responsivenessSortBy,
    responsivenessSortDirection,
    cacheMeta,
    setReviewResponsiveness,
    setResponsivenessLoading,
    setResponsivenessError,
    sortResponsiveness,
    getSortedReviewerLeaderboard,
    setCacheMeta,
  } = useAnalyticsStore()

  useEffect(() => {
    if (selectedRepo) {
      loadResponsiveness()
    }
  }, [selectedRepo])

  const loadResponsiveness = async () => {
    if (!selectedRepo) return

    try {
      setResponsivenessLoading(true)
      setResponsivenessError(null)
      const response = await fetchReviewResponsiveness(
        selectedRepo.owner.login,
        selectedRepo.name
      )
      setReviewResponsiveness(response)
      setCacheMeta('responsiveness', response)
    } catch (err) {
      setResponsivenessError(err instanceof Error ? err.message : 'Failed to load responsiveness data')
    } finally {
      setResponsivenessLoading(false)
    }
  }

  if (responsivenessLoading) {
    return (
      <div className="mx-analytics__loading">
        <Spinner size="lg" />
        <p>Loading review responsiveness...</p>
      </div>
    )
  }

  if (responsivenessError) {
    return <Alert variant="error">{responsivenessError}</Alert>
  }

  if (!reviewResponsiveness) return null

  const sortedLeaderboard = getSortedReviewerLeaderboard()

  const columns: Column<any>[] = [
    { key: 'reviewer', label: 'Reviewer', sortable: true, tooltip: 'GitHub username of the reviewer' },
    {
      key: 'avg_response_time_hours',
      label: 'Avg Response',
      sortable: true,
      tooltip: 'Average time from PR creation to review',
      render: (r) => formatHours(r.avg_response_time_hours),
    },
    {
      key: 'median_response_time_hours',
      label: 'Median Response',
      sortable: true,
      tooltip: 'Median time from PR creation to review',
      render: (r) => formatHours(r.median_response_time_hours),
    },
    {
      key: 'total_reviews',
      label: 'Total Reviews',
      sortable: true,
      tooltip: 'Total number of reviews submitted by this reviewer',
      render: (r) => formatNumber(r.total_reviews),
    },
    {
      key: 'approvals',
      label: 'Approvals',
      sortable: true,
      tooltip: 'Number of PRs this reviewer approved',
      render: (r) => formatNumber(r.approvals),
    },
    {
      key: 'changes_requested',
      label: 'Changes Req.',
      sortable: true,
      tooltip: 'Number of times this reviewer requested changes',
      render: (r) => formatNumber(r.changes_requested),
    },
    {
      key: 'approval_rate',
      label: 'Approval Rate',
      sortable: true,
      tooltip: 'Percentage of reviews that were approvals',
      render: (r) => `${r.approval_rate.toFixed(1)}%`,
    },
  ]

  const responsivenessCacheMeta = cacheMeta.responsiveness

  return (
    <div className="mx-responsiveness-view">
      <CacheTimestamp
        lastUpdated={responsivenessCacheMeta.lastUpdated}
        stale={responsivenessCacheMeta.stale}
        refreshing={responsivenessCacheMeta.refreshing}
      />
      <div className="mx-stat-cards">
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Avg Team Response</span>
          <span className="mx-stat-card__value">
            {formatHours(reviewResponsiveness.avg_team_response_hours)}
          </span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">Fastest Reviewer</span>
          <span className="mx-stat-card__value">
            {reviewResponsiveness.fastest_reviewer}
          </span>
        </div>
        <div className="mx-stat-card">
          <span className="mx-stat-card__label">PRs Awaiting Review</span>
          <span className="mx-stat-card__value">
            {reviewResponsiveness.prs_awaiting_review}
          </span>
        </div>
      </div>

      <h3>Reviewer Leaderboard</h3>
      <SortableTable
        columns={columns}
        data={sortedLeaderboard}
        sortBy={responsivenessSortBy}
        sortDirection={responsivenessSortDirection}
        onSort={sortResponsiveness}
        keyExtractor={(r) => r.reviewer}
      />

      {reviewResponsiveness.bottlenecks.length > 0 && (
        <div className="mx-bottlenecks">
          <h3>Review Bottlenecks</h3>
          <Alert variant="warning">
            <strong>Top PRs waiting for review:</strong>
            <ul className="mx-bottleneck-list">
              {reviewResponsiveness.bottlenecks.slice(0, 10).map((b) => (
                <li key={b.number}>
                  PR #{b.number}: {b.title} - waiting {formatHours(b.wait_hours)}
                </li>
              ))}
            </ul>
          </Alert>
        </div>
      )}
    </div>
  )
}
