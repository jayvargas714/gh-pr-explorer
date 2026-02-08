import { useEffect } from 'react'
import { useAnalyticsStore } from '../../stores/useAnalyticsStore'
import { useAccountStore } from '../../stores/useAccountStore'
import { fetchDeveloperStats } from '../../api/analytics'
import { SortableTable, Column } from '../common/SortableTable'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'
import { formatNumber, calculatePercentage } from '../../utils/formatters'
import { DeveloperStats } from '../../api/types'

export function StatsView() {
  const selectedRepo = useAccountStore((state) => state.selectedRepo)
  const {
    statsLoading,
    statsError,
    statsSortBy,
    statsSortDirection,
    setDeveloperStats,
    setStatsLoading,
    setStatsError,
    sortStats,
    getSortedStats,
  } = useAnalyticsStore()

  useEffect(() => {
    if (selectedRepo) {
      loadStats()
    }
  }, [selectedRepo])

  const loadStats = async () => {
    if (!selectedRepo) return

    try {
      setStatsLoading(true)
      setStatsError(null)
      const response = await fetchDeveloperStats(
        selectedRepo.owner.login,
        selectedRepo.name
      )
      setDeveloperStats(response.stats)
    } catch (err) {
      setStatsError(err instanceof Error ? err.message : 'Failed to load stats')
    } finally {
      setStatsLoading(false)
    }
  }

  if (statsLoading) {
    return (
      <div className="mx-analytics__loading">
        <Spinner size="lg" />
        <p>Loading developer statistics...</p>
      </div>
    )
  }

  if (statsError) {
    return <Alert variant="error">{statsError}</Alert>
  }

  const sortedStats = getSortedStats()

  const columns: Column<DeveloperStats>[] = [
    {
      key: 'login',
      label: 'Developer',
      sortable: true,
      render: (stat) => (
        <div className="mx-stats-developer">
          <img src={stat.avatar_url} alt={stat.login} className="mx-stats-avatar" />
          <span>{stat.login}</span>
        </div>
      ),
    },
    {
      key: 'commits',
      label: 'Commits',
      sortable: true,
      tooltip: 'Total commits to the repository',
      render: (stat) => formatNumber(stat.commits),
    },
    {
      key: 'prs_authored',
      label: 'PRs',
      sortable: true,
      tooltip: 'Total PRs authored',
      render: (stat) => formatNumber(stat.prs_authored),
    },
    {
      key: 'prs_merged',
      label: 'Merged',
      sortable: true,
      tooltip: 'Number of merged PRs',
      render: (stat) => formatNumber(stat.prs_merged),
    },
    {
      key: 'prs_closed',
      label: 'Closed',
      sortable: true,
      tooltip: 'Number of closed (not merged) PRs',
      render: (stat) => formatNumber(stat.prs_closed),
    },
    {
      key: 'merge_rate',
      label: 'Merge %',
      sortable: false,
      tooltip: 'Percentage of authored PRs that were merged',
      render: (stat) => {
        const rate = calculatePercentage(stat.prs_merged, stat.prs_authored)
        return <span className="mx-stats-merge-rate">{rate.toFixed(1)}%</span>
      },
    },
    {
      key: 'reviews_given',
      label: 'Reviews',
      sortable: true,
      tooltip: 'Total reviews given',
      render: (stat) => formatNumber(stat.reviews_given),
    },
    {
      key: 'approvals',
      label: 'Approvals',
      sortable: true,
      tooltip: 'Number of approval reviews',
      render: (stat) => formatNumber(stat.approvals),
    },
    {
      key: 'changes_requested',
      label: 'Changes Req.',
      sortable: true,
      tooltip: 'Number of "changes requested" reviews',
      render: (stat) => formatNumber(stat.changes_requested),
    },
    {
      key: 'lines_added',
      label: 'Lines +',
      sortable: true,
      tooltip: 'Total lines added',
      render: (stat) => (
        <span className="mx-stats-additions">{formatNumber(stat.lines_added)}</span>
      ),
    },
    {
      key: 'lines_deleted',
      label: 'Lines -',
      sortable: true,
      tooltip: 'Total lines deleted',
      render: (stat) => (
        <span className="mx-stats-deletions">{formatNumber(stat.lines_deleted)}</span>
      ),
    },
  ]

  return (
    <div className="mx-stats-view">
      <SortableTable
        columns={columns}
        data={sortedStats}
        sortBy={statsSortBy}
        sortDirection={statsSortDirection}
        onSort={sortStats}
        keyExtractor={(stat) => stat.login}
        className="mx-stats-table"
      />
    </div>
  )
}
