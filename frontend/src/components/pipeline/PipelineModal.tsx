import { useCallback, useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useUIStore } from '../../stores/useUIStore'
import { usePipelineStore } from '../../stores/usePipelineStore'
import { PipelineHeader } from './PipelineHeader'
import { PipelineTable } from './PipelineTable'
import { BulkActionBar } from './BulkActionBar'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'

// The pipeline endpoint is served from an in-memory snapshot (zero `gh`
// calls), and the client sends its version so unchanged polls are one tiny
// JSON reply — a tight cadence is affordable here, unlike the swimlane board.
const POLL_INTERVAL_MS = 10_000

/** Full-screen slide-in overlay listing every PR the automation pipeline is
 * holding or has handled. The store keeps its rows for the page lifetime, so
 * reopening renders instantly and refreshes in the background. */
export function PipelineModal() {
  const isOpen = useUIStore((s) => s.showPipeline)
  const close = useUIStore((s) => s.setShowPipeline)
  const load = usePipelineStore((s) => s.load)
  const refresh = usePipelineStore((s) => s.refresh)
  const loading = usePipelineStore((s) => s.loading)
  const error = usePipelineStore((s) => s.error)
  const hasRows = usePipelineStore((s) => s.rows.length > 0)

  const handleClose = useCallback(() => close(false), [close])

  useEffect(() => {
    if (!isOpen) return
    load()
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
  }, [isOpen, load, handleClose])

  // Background polling while open and visible; refresh immediately when the
  // tab regains visibility so a returning user doesn't stare at stale rows.
  useEffect(() => {
    if (!isOpen) return
    const tick = () => {
      if (document.visibilityState !== 'visible') return
      refresh()
    }
    const timer = window.setInterval(tick, POLL_INTERVAL_MS)
    const onVisibility = () => {
      if (document.visibilityState === 'visible') refresh()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [isOpen, refresh])

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          key="pipe-modal"
          className="mx-pipe-modal__overlay"
          onClick={handleClose}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, pointerEvents: 'none' }}
          transition={{ duration: 0.18 }}
          role="dialog"
          aria-modal="true"
          aria-label="Automation Pipeline"
        >
          <motion.div
            className="mx-pipe-modal__shell"
            onClick={(e) => e.stopPropagation()}
            initial={{ opacity: 0, x: 60, scale: 0.98 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 60, scale: 0.98 }}
            transition={{ type: 'spring', damping: 28, stiffness: 320 }}
          >
            <PipelineHeader onClose={handleClose} onRefresh={load} />

            <div className="mx-pipe-modal__body">
              {error && <Alert variant="error">{error}</Alert>}
              {loading && !hasRows ? (
                <div className="mx-pipe-modal__loading">
                  <Spinner size="md" />
                  <p>Loading pipeline…</p>
                </div>
              ) : (
                <>
                  <BulkActionBar />
                  <PipelineTable />
                </>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
