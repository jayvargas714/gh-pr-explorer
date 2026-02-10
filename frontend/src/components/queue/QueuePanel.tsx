import { useEffect } from 'react'
import { useQueueStore } from '../../stores/useQueueStore'
import { useUIStore } from '../../stores/useUIStore'
import { fetchMergeQueue } from '../../api/queue'
import { QueueItem } from './QueueItem'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'
import { Button } from '../common/Button'

export function QueuePanel() {
  const showQueuePanel = useUIStore((state) => state.showQueuePanel)
  const setShowQueuePanel = useUIStore((state) => state.setShowQueuePanel)
  const { mergeQueue, loading: queueLoading, error: queueError, setMergeQueue, setLoading: setQueueLoading, setError: setQueueError } =
    useQueueStore()

  useEffect(() => {
    if (showQueuePanel) {
      loadQueue()
    }
  }, [showQueuePanel])

  const loadQueue = async () => {
    try {
      setQueueLoading(true)
      setQueueError(null)
      const response = await fetchMergeQueue()
      setMergeQueue(response.queue)
    } catch (err) {
      setQueueError(err instanceof Error ? err.message : 'Failed to load merge queue')
    } finally {
      setQueueLoading(false)
    }
  }

  if (!showQueuePanel) return null

  return (
    <>
      {/* Overlay */}
      <div className="mx-queue-overlay" onClick={() => setShowQueuePanel(false)} />

      {/* Panel */}
      <div className="mx-queue-panel">
        <div className="mx-queue-panel__header">
          <div className="mx-queue-panel__title">
            <h2>Merge Queue</h2>
            <span className="mx-queue-panel__count">
              {mergeQueue.length} {mergeQueue.length === 1 ? 'item' : 'items'}
            </span>
          </div>
          <Button variant="ghost" size="sm" onClick={() => setShowQueuePanel(false)}>
            ✕
          </Button>
        </div>

        <div className="mx-queue-panel__content">
          {queueLoading && mergeQueue.length === 0 ? (
            <div className="mx-queue-panel__loading">
              <Spinner size="md" />
              <p>Loading queue...</p>
            </div>
          ) : queueError ? (
            <Alert variant="error">{queueError}</Alert>
          ) : mergeQueue.length === 0 ? (
            <Alert variant="info">
              No PRs in queue. Click the queue button on any PR card to add it.
            </Alert>
          ) : (
            <div className="mx-queue-panel__list">
              {mergeQueue.map((item, index) => (
                <QueueItem key={item.id} item={item} index={index} onRefresh={loadQueue} />
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
