import { useState } from 'react'
import { PullRequest, DivergenceInfo } from '../../api/types'
import { Badge } from '../common/Badge'
import { ReviewersBadge } from '../common/ReviewersBadge'
import { ChangesRequestedModal } from '../common/ChangesRequestedModal'

interface PRBadgesProps {
  pr: PullRequest
  divergence?: DivergenceInfo
}

export function PRBadges({ pr, divergence }: PRBadgesProps) {
  const [showChangesModal, setShowChangesModal] = useState(false)
  const reviewers = pr.currentReviewers || []

  const getReviewStatusBadge = () => {
    if (!pr.reviewDecision) return null

    switch (pr.reviewDecision) {
      case 'APPROVED':
        return (
          <Badge variant="success" key="review">
            ✓ Approved
          </Badge>
        )
      case 'CHANGES_REQUESTED':
        return (
          <span
            key="review"
            className="mx-badge-clickable"
            onClick={(e) => { e.stopPropagation(); setShowChangesModal(true) }}
          >
            <Badge variant="error">
              ✗ Changes Requested
            </Badge>
          </span>
        )
      case 'REVIEW_REQUIRED':
        return (
          <Badge variant="warning" key="review">
            👀 Review Required
          </Badge>
        )
      default:
        return null
    }
  }

  const getCIStatusBadge = () => {
    if (!pr.ciStatus) return null

    switch (pr.ciStatus.toLowerCase()) {
      case 'success':
        return (
          <Badge variant="success" key="ci">
            ✓ CI Passed
          </Badge>
        )
      case 'failure':
        return (
          <Badge variant="error" key="ci">
            ✗ CI Failed
          </Badge>
        )
      case 'pending':
        return (
          <Badge variant="warning" key="ci">
            ⏳ CI Running
          </Badge>
        )
      default:
        return (
          <Badge variant="neutral" key="ci">
            CI Skipped
          </Badge>
        )
    }
  }

  const getDivergenceBadge = () => {
    if (!divergence || pr.state !== 'OPEN') return null

    const { behind_by } = divergence

    if (behind_by === 0) {
      return (
        <Badge variant="success" key="divergence">
          ✓ Up to date
        </Badge>
      )
    } else if (behind_by <= 10) {
      return (
        <Badge variant="warning" key="divergence">
          ⚠ {behind_by} behind
        </Badge>
      )
    } else {
      return (
        <Badge variant="error" key="divergence">
          ⚠ {behind_by} behind
        </Badge>
      )
    }
  }

  const getStateBadge = () => {
    if (pr.state === 'MERGED') {
      return (
        <Badge variant="info" key="state">
          Merged
        </Badge>
      )
    } else if (pr.state === 'CLOSED') {
      return (
        <Badge variant="neutral" key="state">
          Closed
        </Badge>
      )
    }
    return null
  }

  const badges = [
    getStateBadge(),
    getReviewStatusBadge(),
    reviewers.length > 0 ? <ReviewersBadge key="reviewers" reviewers={reviewers} /> : null,
    getCIStatusBadge(),
    getDivergenceBadge(),
  ].filter(Boolean)

  if (badges.length === 0 && !showChangesModal) return null

  return (
    <>
      {badges.length > 0 && <div className="mx-pr-card__badges">{badges}</div>}
      {showChangesModal && (
        <ChangesRequestedModal
          reviewers={reviewers}
          onClose={() => setShowChangesModal(false)}
        />
      )}
    </>
  )
}
