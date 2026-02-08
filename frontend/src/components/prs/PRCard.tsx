import { useState } from 'react'
import { PullRequest } from '../../api/types'
import { usePRStore } from '../../stores/usePRStore'
import { useQueueStore } from '../../stores/useQueueStore'
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
  const prDivergence = usePRStore((state) => state.prDivergence)
  const { isInQueue, addToQueue, removeFromQueue } = useQueueStore()

  const divergence = prDivergence[pr.number]
  const inQueue = isInQueue(pr.number, `${pr.author.login}/${pr.baseRefName}`)

  const handleQueueToggle = () => {
    if (inQueue) {
      removeFromQueue(pr.number, `${pr.author.login}/${pr.baseRefName}`)
    } else {
      addToQueue({
        id: 0, // Will be set by backend
        number: pr.number,
        title: pr.title,
        url: pr.url,
        repo: `${pr.author.login}/${pr.baseRefName}`,
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
          title={inQueue ? 'Remove from queue' : 'Add to queue'}
        >
          {inQueue ? '📋 Queued' : '➕ Queue'}
        </Button>

        <ReviewButton pr={pr} />

        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowDescription(true)}
          title="View description"
        >
          📝
        </Button>

        <Button
          variant="ghost"
          size="sm"
          onClick={() => window.open(pr.url, '_blank')}
          title="Open on GitHub"
        >
          🔗
        </Button>
      </div>

      <DescriptionModal pr={pr} isOpen={showDescription} onClose={() => setShowDescription(false)} />
    </Card>
  )
}
