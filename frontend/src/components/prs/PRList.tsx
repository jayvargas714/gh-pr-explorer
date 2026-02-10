import { useEffect, useMemo } from 'react'
import { usePRStore, PRReviewInfo } from '../../stores/usePRStore'
import { useAccountStore } from '../../stores/useAccountStore'
import { useFilterStore, getFilterParams } from '../../stores/useFilterStore'
import { fetchPRs, fetchDivergence } from '../../api/prs'
import { fetchReviewHistory } from '../../api/reviews'
import { PRCard } from './PRCard'
import { Pagination } from '../common/Pagination'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'

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

  useEffect(() => {
    if (selectedRepo) {
      loadPRs()
    }
  }, [selectedRepo, filters])

  const loadPRs = async () => {
    if (!selectedRepo) return

    try {
      setLoading(true)
      setError(null)

      const response = await fetchPRs(
        selectedRepo.owner.login,
        selectedRepo.name,
        filters
      )

      setPRs(response.prs)

      // Fetch divergence for open PRs
      const openPRs = response.prs.filter((pr) => pr.state === 'OPEN')
      if (openPRs.length > 0) {
        loadDivergence(openPRs)
      }

      // Fetch review scores for displayed PRs
      loadReviewScores()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load pull requests')
    } finally {
      setLoading(false)
    }
  }

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

  const paginatedPRs = getPaginatedPRs()
  const totalPages = getTotalPages()

  return (
    <div className="mx-pr-list">
      <div className="mx-pr-list__header">
        <h2>{prs.length} Pull Requests</h2>
      </div>

      <div className="mx-pr-list__items">
        {paginatedPRs.map((pr) => (
          <PRCard key={pr.number} pr={pr} />
        ))}
      </div>

      {totalPages > 1 && (
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
