import { PullRequest, DivergenceInfo, Reviewer } from '../../api/types'
import { Badge } from '../common/Badge'

const REVIEW_STATE_ICON: Record<string, string> = {
  APPROVED: '✓',
  CHANGES_REQUESTED: '✗',
  COMMENTED: '💬',
  DISMISSED: '—',
}

function buildReviewerTooltip(reviewers: Reviewer[]): string {
  if (!reviewers.length) return ''
  return reviewers
    .map((r) => `${REVIEW_STATE_ICON[r.state] || '?'} ${r.login} — ${r.state.replace('_', ' ').toLowerCase()}`)
    .join('\n')
}

interface PRBadgesProps {
  pr: PullRequest
  divergence?: DivergenceInfo
}

export function PRBadges({ pr, divergence }: PRBadgesProps) {
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
          <Badge variant="error" key="review">
            ✗ Changes Requested
          </Badge>
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

  const getReviewerBadges = () => {
    if (!reviewers.length) return null
    return (
      <span
        key="reviewers"
        className="mx-pr-card__reviewers"
        data-tooltip={buildReviewerTooltip(reviewers)}
      >
        {reviewers.map((r) => (
          <span
            key={r.login}
            className={`mx-pr-card__reviewer mx-pr-card__reviewer--${r.state.toLowerCase().replace('_', '-')}`}
          >
            {r.avatarUrl ? (
              <img
                src={r.avatarUrl}
                alt={r.login}
                className="mx-pr-card__reviewer-avatar"
              />
            ) : null}
            <span className="mx-pr-card__reviewer-icon">
              {REVIEW_STATE_ICON[r.state] || '?'}
            </span>
          </span>
        ))}
      </span>
    )
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
    getReviewerBadges(),
    getCIStatusBadge(),
    getDivergenceBadge(),
  ].filter(Boolean)

  if (badges.length === 0) return null

  return <div className="mx-pr-card__badges">{badges}</div>
}
