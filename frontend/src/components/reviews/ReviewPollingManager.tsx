import { useEffect } from 'react'
import { useReviewStore } from '../../stores/useReviewStore'
import { useAuditStore } from '../../stores/useAuditStore'
import { fetchActiveReviews } from '../../api/reviews'

// Reviews are started server-side too (automation dispatch, review requests,
// auto follow-ups), so the client cannot gate polling on whether *it* knows of
// a running review — that is exactly the state it would never learn about.
// `/api/reviews` is an in-memory read (no gh calls), so a steady poll is cheap.
const POLL_INTERVAL_MS = 5_000

export function ReviewPollingManager() {
  useEffect(() => {
    const poll = async () => {
      try {
        const response = await fetchActiveReviews()
        useReviewStore.getState().setActiveReviews(response.reviews)
      } catch (err) {
        console.error('Failed to poll reviews:', err)
      }
      useAuditStore.getState().refreshActiveAudits()
    }

    // Immediate fetch recovers state after a page load; the interval keeps every
    // surface (PR list, merge queue, swimlanes, pipeline) in step with the server.
    poll()
    const tick = () => {
      if (document.visibilityState !== 'visible') return
      poll()
    }
    const timer = window.setInterval(tick, POLL_INTERVAL_MS)
    const onVisibility = () => {
      if (document.visibilityState === 'visible') poll()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  return null
}
