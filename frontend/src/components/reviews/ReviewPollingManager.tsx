import { useEffect, useMemo, useRef } from 'react'
import { useReviewStore } from '../../stores/useReviewStore'
import { fetchActiveReviews } from '../../api/reviews'

export function ReviewPollingManager() {
  const activeReviews = useReviewStore((state) => state.activeReviews)
  const initialFetchDone = useRef(false)

  const hasRunning = useMemo(
    () =>
      Object.values(activeReviews).some(
        (review) => review.status === 'running'
      ),
    [activeReviews]
  )

  // Fetch active reviews once on mount to recover from page refresh
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
  }, [])

  // Poll every 5 seconds while there are running reviews
  useEffect(() => {
    if (!hasRunning) return

    const pollReviews = async () => {
      try {
        const response = await fetchActiveReviews()
        useReviewStore.getState().setActiveReviews(response.reviews)
      } catch (err) {
        console.error('Failed to poll reviews:', err)
      }
    }

    const interval = setInterval(pollReviews, 5000)

    return () => clearInterval(interval)
  }, [hasRunning])

  return null
}
