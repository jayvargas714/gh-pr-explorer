import { useState } from 'react'
import { useQueueStore } from '../../stores/useQueueStore'
import { removeFromQueue, reorderQueue } from '../../api/queue'
import { NotesModal } from './NotesModal'
import { Button } from '../common/Button'
import { Badge } from '../common/Badge'
import { formatNumber, formatRelativeTime } from '../../utils/formatters'
import type { MergeQueueItem } from '../../api/types'

interface QueueItemProps {
  item: MergeQueueItem
  index: number
  onRefresh: () => void
}

export function QueueItem({ item, index, onRefresh }: QueueItemProps) {
  const [showNotes, setShowNotes] = useState(false)
  const [moving, setMoving] = useState(false)
  const [removing, setRemoving] = useState(false)
  const mergeQueue = useQueueStore((state) => state.mergeQueue)

  const handleRemove = async () => {
    if (removing) return
    try {
      setRemoving(true)
      await removeFromQueue(item.number, item.repo)
      onRefresh()
    } catch (err) {
      console.error('Failed to remove from queue:', err)
    } finally {
      setRemoving(false)
    }
  }

  const handleMove = async (direction: 'up' | 'down') => {
    if (moving) return
    const toIndex = direction === 'up' ? index - 1 : index + 1
    if (toIndex < 0 || toIndex >= mergeQueue.length) return

    try {
      setMoving(true)
      await reorderQueue(index, toIndex)
      onRefresh()
    } catch (err) {
      console.error('Failed to reorder queue:', err)
    } finally {
      setMoving(false)
    }
  }

  const getStateBadge = () => {
    switch (item.prState) {
      case 'OPEN':
        return <Badge variant="success">Open</Badge>
      case 'CLOSED':
        return <Badge variant="neutral">Closed</Badge>
      case 'MERGED':
        return <Badge variant="info">Merged</Badge>
      default:
        return null
    }
  }

  return (
    <>
      <div className="mx-queue-item">
        <div className="mx-queue-item__header">
          <div className="mx-queue-item__position">{index + 1}</div>
          <div className="mx-queue-item__info">
            <div className="mx-queue-item__title-row">
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="mx-queue-item__title"
              >
                #{item.number} {item.title}
              </a>
              {getStateBadge()}
            </div>
            <div className="mx-queue-item__meta">
              <span className="mx-queue-item__repo">{item.repo}</span>
              <span className="mx-queue-item__author">by {item.author}</span>
              <span className="mx-queue-item__time">{formatRelativeTime(item.addedAt)}</span>
            </div>
          </div>
        </div>

        <div className="mx-queue-item__stats">
          <span className="mx-stats-additions">+{formatNumber(item.additions)}</span>
          <span className="mx-stats-deletions">-{formatNumber(item.deletions)}</span>
        </div>

        {item.hasReview && (
          <div className="mx-queue-item__badges">
            {item.reviewScore !== null && item.reviewScore !== undefined && (
              <Badge
                variant={
                  item.reviewScore >= 7 ? 'success' : item.reviewScore >= 4 ? 'warning' : 'error'
                }
              >
                Score: {item.reviewScore}/10
              </Badge>
            )}
            {item.hasNewCommits && <Badge variant="warning">New Commits</Badge>}
            {item.inlineCommentsPosted && <Badge variant="info">Posted</Badge>}
          </div>
        )}

        <div className="mx-queue-item__actions">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => handleMove('up')}
            disabled={index === 0 || moving}
          >
            ↑
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => handleMove('down')}
            disabled={index === mergeQueue.length - 1 || moving}
          >
            ↓
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setShowNotes(true)}>
            Notes {item.notesCount > 0 && `(${item.notesCount})`}
          </Button>
          <Button variant="ghost" size="sm" onClick={handleRemove} disabled={removing}>
            Remove
          </Button>
        </div>
      </div>

      {showNotes && (
        <NotesModal
          prNumber={item.number}
          repo={item.repo}
          onClose={() => setShowNotes(false)}
          onUpdate={onRefresh}
        />
      )}
    </>
  )
}
