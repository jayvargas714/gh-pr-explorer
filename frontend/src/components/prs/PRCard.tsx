import { useState } from 'react'
import { PullRequest } from '../../api/types'
import { usePRStore } from '../../stores/usePRStore'
import { useAccountStore } from '../../stores/useAccountStore'
import { useQueueStore } from '../../stores/useQueueStore'
import { useReviewStore } from '../../stores/useReviewStore'
import { addToQueue as apiAddToQueue, removeFromQueue as apiRemoveFromQueue } from '../../api/queue'
import { fetchMergeQueue } from '../../api/queue'
import { Card } from '../common/Card'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { PRBadges } from './PRBadges'
import { ReviewButton } from '../reviews/ReviewButton'
import { DescriptionModal } from '../modals/DescriptionModal'
import { formatRelativeTime } from '../../utils/formatters'

interface PRCardProps {
  pr: PullRequest
}

export function PRCard({ pr }: PRCardProps) {
  const [showDescription, setShowDescription] = useState(false)
  const [queueLoading, setQueueLoading] = useState(false)
  const prDivergence = usePRStore((state) => state.prDivergence)
  const prReviewScores = usePRStore((state) => state.prReviewScores)
  const selectedRepo = useAccountStore((state) => state.selectedRepo)
  const { isInQueue, setMergeQueue, addToQueue: addToQueueStore, removeFromQueue: removeFromQueueStore } = useQueueStore()
  const openReviewViewer = useReviewStore((state) => state.openReviewViewer)

  const reviewInfo = prReviewScores[pr.number]

  const repoFullName = selectedRepo ? `${selectedRepo.owner.login}/${selectedRepo.name}` : ''
  const divergence = prDivergence[pr.number]
  const inQueue = isInQueue(pr.number, repoFullName)

  const handleQueueToggle = async () => {
    if (queueLoading) return
    try {
      setQueueLoading(true)
      if (inQueue) {
        // Optimistic removal
        removeFromQueueStore(pr.number, repoFullName)
        await apiRemoveFromQueue(pr.number, repoFullName)
      } else {
        // Optimistic add with placeholder item
        addToQueueStore({
          id: Date.now(),
          number: pr.number,
          title: pr.title,
          url: pr.url,
          repo: repoFullName,
          author: pr.author.login,
          additions: pr.additions,
          deletions: pr.deletions,
          addedAt: new Date().toISOString(),
          notesCount: 0,
          prState: pr.state,
          hasNewCommits: false,
          lastReviewedSha: null,
          currentSha: null,
          hasReview: false,
          reviewScore: null,
          reviewId: null,
          inlineCommentsPosted: false,
        })
        await apiAddToQueue({
          number: pr.number,
          title: pr.title,
          url: pr.url,
          repo: repoFullName,
          author: pr.author.login,
          additions: pr.additions,
          deletions: pr.deletions,
        })
      }
      // Background refresh for accurate server state (don't await)
      fetchMergeQueue().then((response) => setMergeQueue(response.queue)).catch(() => {})
    } catch (err) {
      console.error('Failed to update queue:', err)
      // Revert on failure
      fetchMergeQueue().then((response) => setMergeQueue(response.queue)).catch(() => {})
    } finally {
      setQueueLoading(false)
    }
  }

  return (
    <Card className="mx-pr-card" hover>
      <div className="mx-pr-card__header">
        <div className="mx-pr-card__title-area">
          <a
            href={pr.url}
            target="_blank"
            rel="noopener noreferrer"
            className="mx-pr-card__title"
          >
            #{pr.number} {pr.title}
          </a>
          {pr.isDraft && <Badge variant="warning">Draft</Badge>}
        </div>

        <div className="mx-pr-card__meta">
          <img
            src={pr.author.avatarUrl}
            alt={pr.author.login}
            className="mx-pr-card__avatar"
          />
          <span className="mx-pr-card__author">{pr.author.login}</span>
          <span className="mx-pr-card__time">{formatRelativeTime(pr.createdAt)}</span>
        </div>
      </div>

      <PRBadges pr={pr} divergence={divergence} />

      <div className="mx-pr-card__stats">
        <span className="mx-pr-card__stat mx-pr-card__stat--additions">
          +{pr.additions}
        </span>
        <span className="mx-pr-card__stat mx-pr-card__stat--deletions">
          -{pr.deletions}
        </span>
        <span className="mx-pr-card__stat">{pr.changedFiles} files</span>
        <span className="mx-pr-card__branches">
          {pr.headRefName} → {pr.baseRefName}
        </span>
      </div>

      <div className="mx-pr-card__actions">
        <Button
          variant={inQueue ? 'primary' : 'secondary'}
          size="sm"
          onClick={handleQueueToggle}
          disabled={queueLoading}
          data-tooltip={inQueue ? 'Remove from queue' : 'Add to queue'}
        >
          {queueLoading ? '...' : inQueue ? '📋 Queued' : '➕ Queue'}
        </Button>

        <ReviewButton pr={pr} />

        {reviewInfo && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => openReviewViewer({ id: reviewInfo.reviewId })}
            data-tooltip="View review"
            className={`mx-score-btn mx-score-btn--${
              reviewInfo.score !== null && reviewInfo.score !== undefined
                ? reviewInfo.score >= 7 ? 'good' : reviewInfo.score >= 4 ? 'ok' : 'bad'
                : 'neutral'
            }`}
          >
            {reviewInfo.score !== null && reviewInfo.score !== undefined
              ? `${reviewInfo.score}/10`
              : 'Reviewed'}
          </Button>
        )}

        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowDescription(true)}
          data-tooltip="View description"
        >
          📝
        </Button>

        <Button
          variant="ghost"
          size="sm"
          onClick={() => window.open(pr.url, '_blank')}
          data-tooltip="Open on GitHub"
        >
          🔗
        </Button>
      </div>

      <DescriptionModal pr={pr} isOpen={showDescription} onClose={() => setShowDescription(false)} />
    </Card>
  )
}
