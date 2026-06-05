import { useEffect, useMemo, useRef } from 'react'
import { useReviewStore } from '../../stores/useReviewStore'
import { useAuditStore } from '../../stores/useAuditStore'
import { fetchActiveReviews } from '../../api/reviews'

export function ReviewPollingManager() {
  const activeReviews = useReviewStore((state) => state.activeReviews)
  const activeAudits = useAuditStore((state) => state.activeAudits)
  const initialFetchDone = useRef(false)

  const hasRunning = useMemo(
    () =>
      Object.values(activeReviews).some(
        (review) => review.status === 'running'
      ) || activeAudits.some((audit) => audit.status === 'running'),
    [activeReviews, activeAudits]
  )

  // Fetch active reviews + audits once on mount to recover from page refresh
  useEffect(() => {
    if (initialFetchDone.current) return
    initialFetchDone.current = true

    fetchActiveReviews()
      .then((response) => {
        if (response.reviews.length > 0) {
          useReviewStore.getState().setActiveReviews(response.reviews)
        }
      })
      .catch((err) => console.error('Failed to fetch active reviews:', err))

    useAuditStore.getState().refreshActiveAudits()
  }, [])

  // Poll every 5 seconds while there are running reviews or audits
  useEffect(() => {
    if (!hasRunning) return

    const pollReviews = async () => {
      try {
        const response = await fetchActiveReviews()
        useReviewStore.getState().setActiveReviews(response.reviews)
      } catch (err) {
        console.error('Failed to poll reviews:', err)
      }
      useAuditStore.getState().refreshActiveAudits()
    }

    const interval = setInterval(pollReviews, 5000)

    return () => clearInterval(interval)
  }, [hasRunning])

  return null
}
