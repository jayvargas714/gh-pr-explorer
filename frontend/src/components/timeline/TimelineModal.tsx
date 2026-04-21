import { useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useTimelineStore } from '../../stores/useTimelineStore'
import { TimelineHeader } from './TimelineHeader'
import { TimelineFilters } from './TimelineFilters'
import { TimelineView } from './TimelineView'

export function TimelineModal() {
  const openFor = useTimelineStore((s) => s.openFor)
  const close = useTimelineStore((s) => s.close)
  const startPolling = useTimelineStore((s) => s.startPolling)
  const stopPolling = useTimelineStore((s) => s.stopPolling)

  useEffect(() => {
    if (!openFor) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    const key = `${openFor.owner}/${openFor.repo}/${openFor.prNumber}`

    window.addEventListener('keydown', onKey)
    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    // Start polling once the initial load has a chance to populate prState.
    const pollStarter = window.setTimeout(() => startPolling(key), 200)

    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = originalOverflow
      window.clearTimeout(pollStarter)
      stopPolling(key)
    }
  }, [openFor, close, startPolling, stopPolling])

  return (
    <AnimatePresence>
      {openFor && (
        <motion.div
          key="timeline-modal"
          className="tl-modal__overlay"
          onClick={close}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, pointerEvents: 'none' }}
          transition={{ duration: 0.18 }}
          role="dialog"
          aria-modal="true"
          aria-label={`Timeline for PR #${openFor.prNumber}`}
        >
          <motion.div
            className="tl-modal__shell"
            onClick={(e) => e.stopPropagation()}
            initial={{ opacity: 0, y: 20, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.98 }}
            transition={{ type: 'spring', damping: 28, stiffness: 320 }}
          >
            <TimelineHeader
              owner={openFor.owner}
              repo={openFor.repo}
              prNumber={openFor.prNumber}
              title={openFor.title}
              url={openFor.url}
            />
            <TimelineFilters
              owner={openFor.owner}
              repo={openFor.repo}
              prNumber={openFor.prNumber}
            />
            <div className="tl-modal__body">
              <TimelineView
                owner={openFor.owner}
                repo={openFor.repo}
                prNumber={openFor.prNumber}
              />
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
