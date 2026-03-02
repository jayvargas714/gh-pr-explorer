import { useEffect } from 'react'
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  verticalListSortingStrategy,
  sortableKeyboardCoordinates,
} from '@dnd-kit/sortable'
import { useQueueStore } from '../../stores/useQueueStore'
import { useUIStore } from '../../stores/useUIStore'
import { fetchMergeQueue, reorderQueue } from '../../api/queue'
import { QueueItem } from './QueueItem'
import { Spinner } from '../common/Spinner'
import { Alert } from '../common/Alert'
import { Button } from '../common/Button'

export function QueuePanel() {
  const showQueuePanel = useUIStore((state) => state.showQueuePanel)
  const setShowQueuePanel = useUIStore((state) => state.setShowQueuePanel)
  const { mergeQueue, loading: queueLoading, error: queueError, setMergeQueue, setLoading: setQueueLoading, setError: setQueueError } =
    useQueueStore()

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  )

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

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return

    const oldIndex = mergeQueue.findIndex((item) => item.id === active.id)
    const newIndex = mergeQueue.findIndex((item) => item.id === over.id)
    if (oldIndex === -1 || newIndex === -1) return

    // Optimistic reorder
    const newQueue = [...mergeQueue]
    const [moved] = newQueue.splice(oldIndex, 1)
    newQueue.splice(newIndex, 0, moved)
    setMergeQueue(newQueue)

    // Persist to backend
    try {
      const order = newQueue.map((q) => ({ number: q.number, repo: q.repo }))
      await reorderQueue(order)
    } catch (err) {
      console.error('Failed to reorder queue:', err)
      // Revert on failure
      loadQueue()
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
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
            >
              <SortableContext
                items={mergeQueue.map((item) => item.id)}
                strategy={verticalListSortingStrategy}
              >
                <div className="mx-queue-panel__list">
                  {mergeQueue.map((item, index) => (
                    <QueueItem key={item.id} item={item} index={index} onRefresh={loadQueue} />
                  ))}
                </div>
              </SortableContext>
            </DndContext>
          )}
        </div>
      </div>
    </>
  )
}
