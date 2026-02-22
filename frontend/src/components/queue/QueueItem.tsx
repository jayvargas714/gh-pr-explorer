import { useState } from 'react'
import { useQueueStore } from '../../stores/useQueueStore'
import { useReviewStore } from '../../stores/useReviewStore'
import { removeFromQueue, reorderQueue } from '../../api/queue'
import { NotesModal } from './NotesModal'
import { QueueReviewButton } from '../reviews/QueueReviewButton'
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
  const openReviewViewer = useReviewStore((state) => state.openReviewViewer)

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
      // Build new order by swapping the items locally, then send full order to backend
      const newQueue = [...mergeQueue]
      const [removed] = newQueue.splice(index, 1)
      newQueue.splice(toIndex, 0, removed)
      const order = newQueue.map((q) => ({ number: q.number, repo: q.repo }))
      await reorderQueue(order)
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
            {item.hasNewCommits && <Badge variant="warning">New Commits</Badge>}
            {item.inlineCommentsPosted && <Badge variant="info">Critical Posted</Badge>}
            {item.majorConcernsPosted && <Badge variant="info">Major Posted</Badge>}
            {item.minorIssuesPosted && <Badge variant="info">Minor Posted</Badge>}
          </div>
        )}

        <div className="mx-queue-item__actions">
          {item.hasReview && item.reviewId && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => openReviewViewer({ id: item.reviewId })}
              data-tooltip="View review"
              className={`mx-score-btn mx-score-btn--${
                item.reviewScore !== null && item.reviewScore !== undefined
                  ? item.reviewScore >= 7 ? 'good' : item.reviewScore >= 4 ? 'ok' : 'bad'
                  : 'neutral'
              }`}
            >
              {item.reviewScore !== null && item.reviewScore !== undefined
                ? `${item.reviewScore}/10`
                : 'View Review'}
            </Button>
          )}
          <QueueReviewButton item={item} onRefresh={onRefresh} />
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
