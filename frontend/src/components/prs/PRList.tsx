import { useCallback, useEffect, useMemo, useRef } from 'react'
import { usePRStore, PRReviewInfo } from '../../stores/usePRStore'
import { useAccountStore } from '../../stores/useAccountStore'
import { useFilterStore, getFilterParams } from '../../stores/useFilterStore'
import { usePolling } from '../../hooks/usePolling'
import { fetchPRs, fetchDivergence } from '../../api/prs'
import { fetchReviewHistory } from '../../api/reviews'
import { PRCard } from './PRCard'
import { Pagination } from '../common/Pagination'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'
import { Button } from '../common/Button'

const PR_POLL_INTERVAL = 60_000 // 60 seconds

export function PRList() {
  const selectedRepo = useAccountStore((state) => state.selectedRepo)
  const filterState = useFilterStore()
  const filters = useMemo(() => getFilterParams(filterState), [filterState])
  const {
    prs,
    loading,
    error,
    currentPage,
    setPRs,
    setLoading,
    setError,
    setCurrentPage,
    getPaginatedPRs,
    getTotalPages,
    setPRDivergence,
    setDivergenceLoading,
    setPRReviewScores,
  } = usePRStore()

  // Track whether initial load has happened to distinguish user-initiated vs silent refresh
  const hasLoadedRef = useRef(false)

  const loadPRs = useCallback(async (silent = false) => {
    if (!selectedRepo) return

    try {
      if (!silent) {
        setLoading(true)
        setError(null)
      }

      const response = await fetchPRs(
        selectedRepo.owner.login,
        selectedRepo.name,
        filters
      )

      // On silent refresh, preserve current page position
      setPRs(response.prs, !silent)

      // Fetch divergence for open PRs
      const openPRs = response.prs.filter((pr) => pr.state === 'OPEN')
      if (openPRs.length > 0) {
        loadDivergence(openPRs)
      }

      // Fetch review scores for displayed PRs
      loadReviewScores()
      hasLoadedRef.current = true
    } catch (err) {
      // Only show errors for user-initiated loads, not silent refreshes
      if (!silent) {
        setError(err instanceof Error ? err.message : 'Failed to load pull requests')
      }
    } finally {
      if (!silent) {
        setLoading(false)
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRepo, filters])

  useEffect(() => {
    if (selectedRepo) {
      hasLoadedRef.current = false
      loadPRs()
    }
  }, [selectedRepo, filters, loadPRs])

  // Auto-refresh PR data every 60s to keep CI status, review status, etc. current
  const silentRefresh = useCallback(() => {
    if (hasLoadedRef.current) {
      loadPRs(true)
    }
  }, [loadPRs])

  usePolling(silentRefresh, PR_POLL_INTERVAL, !!selectedRepo)

  const loadDivergence = async (openPRs: any[]) => {
    if (!selectedRepo) return

    try {
      setDivergenceLoading(true)
      const prData = openPRs.map((pr) => ({
        number: pr.number,
        base: pr.baseRefName,
        head: pr.headRefName,
      }))

      const response = await fetchDivergence(
        selectedRepo.owner.login,
        selectedRepo.name,
        prData
      )

      setPRDivergence(response.divergence)
    } catch (err) {
      console.error('Failed to load divergence:', err)
    } finally {
      setDivergenceLoading(false)
    }
  }

  const loadReviewScores = async () => {
    if (!selectedRepo) return

    try {
      const repo = `${selectedRepo.owner.login}/${selectedRepo.name}`
      const response = await fetchReviewHistory({ repo, limit: 200 })

      // Build a map of pr_number -> latest review info (first match per PR is most recent)
      const scores: Record<number, PRReviewInfo> = {}
      for (const review of response.reviews) {
        if (!scores[review.pr_number]) {
          scores[review.pr_number] = {
            reviewId: review.id,
            score: review.score,
          }
        }
      }
      setPRReviewScores(scores)
    } catch (err) {
      console.error('Failed to load review scores:', err)
    }
  }

  // Client-side PR number filter (must be before early returns to satisfy rules of hooks)
  const prNumberFilter = filterState.prNumber
  const filteredPRs = useMemo(() => {
    if (!prNumberFilter) return prs
    const num = parseInt(prNumberFilter, 10)
    if (isNaN(num)) return prs
    return prs.filter((pr) => pr.number === num)
  }, [prs, prNumberFilter])

  if (loading && prs.length === 0) {
    return (
      <div className="mx-pr-list mx-pr-list--loading">
        <Spinner size="lg" />
        <p>Loading pull requests...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="mx-pr-list">
        <Alert variant="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      </div>
    )
  }

  if (prs.length === 0) {
    return (
      <div className="mx-pr-list mx-pr-list--empty">
        <h3>No Pull Requests Found</h3>
        <p>Try adjusting your filters or check back later</p>
      </div>
    )
  }

  const pageSize = 20
  const displayPRs = prNumberFilter
    ? filteredPRs
    : getPaginatedPRs()
  const totalPages = prNumberFilter
    ? Math.ceil(filteredPRs.length / pageSize)
    : getTotalPages()
  const displayCount = prNumberFilter ? filteredPRs.length : prs.length

  return (
    <div className="mx-pr-list">
      <div className="mx-pr-list__header">
        <h2>{displayCount} Pull Requests</h2>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => loadPRs()}
          disabled={loading}
          data-tooltip="Refresh PR list"
        >
          {loading ? <Spinner size="sm" /> : '↻ Refresh'}
        </Button>
      </div>

      <div className="mx-pr-list__items">
        {displayPRs.map((pr) => (
          <PRCard key={pr.number} pr={pr} />
        ))}
      </div>

      {!prNumberFilter && totalPages > 1 && (
        <Pagination
          currentPage={currentPage}
          totalPages={totalPages}
          totalItems={prs.length}
          onPageChange={setCurrentPage}
        />
      )}
    </div>
  )
}
