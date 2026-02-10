import { useEffect } from 'react'
import { useReviewStore } from '../../stores/useReviewStore'
import { fetchActiveReviews } from '../../api/reviews'

export function ReviewPollingManager() {
  const { activeReviews, setActiveReviews } = useReviewStore()

  useEffect(() => {
    // Poll every 5 seconds if there are any active reviews
    const hasActiveReviews = Object.values(activeReviews).some(
      (review) => review.status === 'running'
    )

    if (!hasActiveReviews) return

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
  }, [activeReviews])

  // This component doesn't render anything
  return null
}
