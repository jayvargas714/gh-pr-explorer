import { useCallback, useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useUIStore } from '../../stores/useUIStore'
import { useSwimlaneStore } from '../../stores/useSwimlaneStore'
import { SwimlaneHeader } from './SwimlaneHeader'
import { SwimlaneBoard } from './SwimlaneBoard'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'

// Background poll cadence. 45s mirrors the timeline modal — each refresh hits
// `gh pr view` once per queued PR, so a tighter cadence (e.g. 15s) would burn
// through GitHub's authenticated rate limit on large queues.
const POLL_INTERVAL_MS = 45_000

export function SwimlaneModal() {
  const isOpen = useUIStore((s) => s.showSwimlaneBoard)
  const close = useUIStore((s) => s.setShowSwimlaneBoard)
  const loadBoard = useSwimlaneStore((s) => s.loadBoard)
  const refreshBoard = useSwimlaneStore((s) => s.refreshBoard)
  const loading = useSwimlaneStore((s) => s.loading)
  const error = useSwimlaneStore((s) => s.error)
  const lanes = useSwimlaneStore((s) => s.lanes)

  const handleClose = useCallback(() => close(false), [close])

  useEffect(() => {
    if (!isOpen) return
    loadBoard()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleClose()
    }
    window.addEventListener('keydown', onKey)
    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = originalOverflow
    }
  }, [isOpen, loadBoard, handleClose])

  // Background polling while the modal is open. Skips when the tab is hidden
  // or while a drag/mutation has paused polling. Refreshes immediately when
  // the tab regains visibility so a returning user doesn't stare at stale data.
  useEffect(() => {
    if (!isOpen) return
    const tick = () => {
      if (document.visibilityState !== 'visible') return
      refreshBoard()
    }
    const timer = window.setInterval(tick, POLL_INTERVAL_MS)
    const onVisibility = () => {
      if (document.visibilityState === 'visible') refreshBoard()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [isOpen, refreshBoard])

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          key="swl-modal"
          className="mx-swl-modal__overlay"
          onClick={handleClose}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, pointerEvents: 'none' }}
          transition={{ duration: 0.18 }}
          role="dialog"
          aria-modal="true"
          aria-label="Swimlane Board"
        >
          <motion.div
            className="mx-swl-modal__shell"
            onClick={(e) => e.stopPropagation()}
            initial={{ opacity: 0, x: 60, scale: 0.98 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 60, scale: 0.98 }}
            transition={{ type: 'spring', damping: 28, stiffness: 320 }}
          >
            <SwimlaneHeader onClose={handleClose} onRefresh={loadBoard} />

            <div className="mx-swl-modal__body">
              {error && <Alert variant="error">{error}</Alert>}
              {loading && lanes.length === 0 ? (
                <div className="mx-swl-modal__loading">
                  <Spinner size="md" />
                  <p>Loading board…</p>
                </div>
              ) : (
                <SwimlaneBoard onRefresh={loadBoard} />
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
