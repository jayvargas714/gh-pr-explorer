import { useState } from 'react'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useReviewStore } from '../../stores/useReviewStore'
import { removeFromQueue } from '../../api/queue'
import { NotesModal } from './NotesModal'
import { VerdictModal } from './VerdictModal'
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
  const [showVerdict, setShowVerdict] = useState(false)
  const [removing, setRemoving] = useState(false)
  const openReviewViewer = useReviewStore((state) => state.openReviewViewer)

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: item.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  }

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

  const getReviewStatusBadge = () => {
    if (!item.reviewDecision) return null
    switch (item.reviewDecision) {
      case 'APPROVED':
        return <Badge variant="success">✓ Approved</Badge>
      case 'CHANGES_REQUESTED':
        return <Badge variant="error">✗ Changes Requested</Badge>
      case 'REVIEW_REQUIRED':
        return <Badge variant="warning">👀 Review Required</Badge>
      default:
        return null
    }
  }

  const getCIStatusBadge = () => {
    if (!item.ciStatus) return null
    switch (item.ciStatus.toLowerCase()) {
      case 'success':
        return <Badge variant="success">✓ CI Passed</Badge>
      case 'failure':
        return <Badge variant="error">✗ CI Failed</Badge>
      case 'pending':
        return <Badge variant="warning">⏳ CI Running</Badge>
      default:
        return <Badge variant="neutral">CI Skipped</Badge>
    }
  }

  return (
    <>
      <div
        ref={setNodeRef}
        style={style}
        className={`mx-queue-item${isDragging ? ' mx-queue-item--dragging' : ''}`}
      >
        <div className="mx-queue-item__header">
          <button
            className="mx-queue-item__drag-handle"
            {...attributes}
            {...listeners}
            aria-label="Drag to reorder"
          >
            ⠿
          </button>
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
              {getReviewStatusBadge()}
              {getCIStatusBadge()}
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
            {item.inlineCommentsPosted && (
              <Badge variant={item.criticalPostedCount !== null && item.criticalPostedCount < (item.criticalFoundCount ?? 0) ? 'warning' : 'info'}>
                Critical {item.criticalPostedCount ?? '?'}/{item.criticalFoundCount ?? '?'}
              </Badge>
            )}
            {item.majorConcernsPosted && (
              <Badge variant={item.majorPostedCount !== null && item.majorPostedCount < (item.majorFoundCount ?? 0) ? 'warning' : 'info'}>
                Major {item.majorPostedCount ?? '?'}/{item.majorFoundCount ?? '?'}
              </Badge>
            )}
            {item.minorIssuesPosted && (
              <Badge variant={item.minorPostedCount !== null && item.minorPostedCount < (item.minorFoundCount ?? 0) ? 'warning' : 'info'}>
                Minor {item.minorPostedCount ?? '?'}/{item.minorFoundCount ?? '?'}
              </Badge>
            )}
          </div>
        )}

        <div className="mx-queue-item__actions">
          {item.hasReview && item.reviewId && (
            <>
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
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowVerdict(true)}
                data-tooltip="Submit review verdict to GitHub"
              >
                Verdict
              </Button>
            </>
          )}
          <QueueReviewButton item={item} onRefresh={onRefresh} />
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

      {showVerdict && item.reviewId && (
        <VerdictModal
          reviewId={item.reviewId}
          prNumber={item.number}
          repo={item.repo}
          onClose={() => setShowVerdict(false)}
        />
      )}
    </>
  )
}
