import { useEffect, useRef } from 'react'
import { useReviewStore } from '../../stores/useReviewStore'
import { fetchActiveReviews } from '../../api/reviews'

export function ReviewPollingManager() {
  const { activeReviews, setActiveReviews } = useReviewStore()
  const initialFetchDone = useRef(false)

  // Fetch active reviews once on mount to recover from page refresh
  useEffect(() => {
    if (initialFetchDone.current) return
    initialFetchDone.current = true

    fetchActiveReviews()
      .then((response) => {
        if (response.reviews.length > 0) {
          setActiveReviews(response.reviews)
        }
      })
      .catch(() => {})
  }, [setActiveReviews])

  // Poll every 5 seconds while there are running reviews
  useEffect(() => {
    const hasRunning = Object.values(activeReviews).some(
      (review) => review.status === 'running'
    )

    if (!hasRunning) return

    const pollReviews = async () => {
      try {
        const response = await fetchActiveReviews()
        setActiveReviews(response.reviews)
      } catch (err) {
        console.error('Failed to poll reviews:', err)
      }
    }

    const interval = setInterval(pollReviews, 5000)

    return () => clearInterval(interval)
  }, [activeReviews, setActiveReviews])

  return null
}
