import { useState } from 'react'
import type { PipelineRow as PipelineRowData } from '../../api/types'
import { usePipelineStore } from '../../stores/usePipelineStore'
import { useReviewStore } from '../../stores/useReviewStore'
import { useTimelineStore } from '../../stores/useTimelineStore'
import { useAutomationStore } from '../../stores/useAutomationStore'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { AutoVerdictBadge } from '../autoVerdict/AutoVerdictBadge'
import { AutoVerdictConfigModal } from '../autoVerdict/AutoVerdictConfigModal'
import { QueueReviewButton, QueueReviewTarget } from '../reviews/QueueReviewButton'
import { AuditButton } from '../audits/AuditButton'
import { AuditViewer } from '../audits/AuditViewer'
import { RevLogRow, formatLocalDateTime } from '../queue/RevLogBadge'
import { NotesModal } from '../queue/NotesModal'
import { VerdictModal } from '../queue/VerdictModal'
import { QueueDescriptionModal } from '../queue/QueueDescriptionModal'
import { prUrl } from './pipelineFilters'

interface PipelineRowDetailProps {
  row: PipelineRowData
}

function scoreClass(score: number | null): string {
  if (score === null) return 'neutral'
  return score >= 7 ? 'good' : score >= 4 ? 'ok' : 'bad'
}

/** Expanded panel under a pipeline row: rev log, latest review + its
 * actions, and the dispatch record. Composes the same pieces queue cards use. */
export function PipelineRowDetail({ row }: PipelineRowDetailProps) {
  const refresh = usePipelineStore((s) => s.refresh)
  const setCriteriaLocal = usePipelineStore((s) => s.setCriteriaLocal)
  const openReviewViewer = useReviewStore((s) => s.openReviewViewer)
  const openTimeline = useTimelineStore((s) => s.open)
  const reviewers = useAutomationStore((s) => s.reviewers)

  const [auditViewerId, setAuditViewerId] = useState<number | null>(null)
  const [showVerdict, setShowVerdict] = useState(false)
  const [showNotes, setShowNotes] = useState(false)
  const [showDescription, setShowDescription] = useState(false)
  const [overrideOpen, setOverrideOpen] = useState(false)

  const [owner, repoName] = row.repo.split('/')
  const url = prUrl(row)
  const title = row.title ?? `#${row.prNumber}`
  const review = row.review
  const reviewerLabel = (key: string | null) =>
    key ? reviewers.find((r) => r.key === key)?.label ?? key : '—'

  // The review button reads the same fields a queue card carries.
  const reviewTarget: QueueReviewTarget = {
    repo: row.repo,
    number: row.prNumber,
    url,
    title,
    author: row.author ?? '',
    hasReview: review !== null,
    reviewId: review?.reviewId ?? null,
    inlineCommentsPosted: review?.inlineCommentsPosted ?? false,
    majorConcernsPosted: review?.majorConcernsPosted ?? false,
    minorIssuesPosted: review?.minorIssuesPosted ?? false,
    autoVerdict: row.autoVerdict ?? undefined,
  }

  return (
    <div className="mx-pipe-detail" onClick={(e) => e.stopPropagation()}>
      <section className="mx-pipe-detail__section">
        <h4 className="mx-pipe-detail__heading">Rev log</h4>
        {row.revLog.length === 0 ? (
          <p className="mx-pipe-muted">No reviews recorded yet.</p>
        ) : (
          <div className="mx-pipe-detail__revlog">
            {row.revLog.map((e) => (
              <RevLogRow
                key={`${e.kind}-${e.id}`}
                entry={e}
                onOpenReview={(id) => openReviewViewer({ id })}
                onOpenAudit={setAuditViewerId}
              />
            ))}
          </div>
        )}
      </section>

      <section className="mx-pipe-detail__section">
        <h4 className="mx-pipe-detail__heading">Latest review</h4>
        {review ? (
          <div className="mx-pipe-detail__review">
            <div className="mx-pipe-badges">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => openReviewViewer({ id: review.reviewId })}
                data-tooltip="View review"
                className={`mx-score-btn mx-score-btn--${scoreClass(review.score)}`}
              >
                {review.score !== null ? `${review.score}/10` : 'View Review'}
              </Button>
              {review.isFollowup && <Badge variant="info" size="sm">Follow-up</Badge>}
              {row.hasNewCommits && <Badge variant="warning" size="sm">New Commits</Badge>}
              {row.autoVerdict?.last && <AutoVerdictBadge record={row.autoVerdict.last} />}
              <span className="mx-pipe-muted">{formatLocalDateTime(review.createdAt)}</span>
            </div>
            <dl className="mx-pipe-detail__issues">
              <dt>Critical</dt>
              <dd>{review.critical.posted ?? '?'}/{review.critical.found ?? '?'} posted</dd>
              <dt>Major</dt>
              <dd>{review.major.posted ?? '?'}/{review.major.found ?? '?'} posted</dd>
              <dt>Minor</dt>
              <dd>{review.minor.posted ?? '?'}/{review.minor.found ?? '?'} posted</dd>
            </dl>
          </div>
        ) : (
          <p className="mx-pipe-muted">
            {row.running ? 'A review is running now.' : 'No review recorded for this PR.'}
          </p>
        )}

        <div className="mx-pipe-detail__actions">
          <QueueReviewButton item={reviewTarget} onRefresh={refresh} />
          {review && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowVerdict(true)}
              data-tooltip="Submit review verdict to GitHub"
            >
              Verdict
            </Button>
          )}
          <AuditButton
            owner={owner ?? ''}
            repo={repoName ?? ''}
            number={row.prNumber}
            url={url}
            title={title}
            author={row.author ?? undefined}
          />
          <Button
            variant="ghost"
            size="sm"
            onClick={() => openTimeline({ owner, repo: repoName, prNumber: row.prNumber, title, url })}
            data-tooltip="View timeline"
          >
            ⏱
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setShowDescription(true)} data-tooltip="View description">
            📝
          </Button>
          {row.onBoard ? (
            <Button variant="ghost" size="sm" onClick={() => setShowNotes(true)}>
              Notes {row.notesCount > 0 && `(${row.notesCount})`}
            </Button>
          ) : (
            <span className="mx-pipe-muted mx-pipe-detail__hint">
              Notes live on the board — watch this PR (📋) to add some.
            </span>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setOverrideOpen(true)}
            data-tooltip="Per-PR auto-verdict criteria override"
          >
            {row.autoVerdict?.criteriaOverride ? 'Criteria (overridden)…' : 'Criteria override…'}
          </Button>
        </div>
      </section>

      <section className="mx-pipe-detail__section">
        <h4 className="mx-pipe-detail__heading">Dispatch</h4>
        <dl className="mx-pipe-detail__dispatch">
          <dt>Status</dt>
          <dd>
            {row.dispatch.status}
            {row.dispatch.detail && <span className="mx-pipe-muted"> · {row.dispatch.detail}</span>}
          </dd>
          <dt>Reviewer</dt>
          <dd>{reviewerLabel(row.dispatch.reviewerKey)}</dd>
          <dt>Rule</dt>
          <dd>{row.dispatch.ruleName ?? <span className="mx-pipe-muted">default</span>}</dd>
          <dt>Matched rules</dt>
          <dd>{row.dispatch.matchedRules.length > 0 ? row.dispatch.matchedRules.join(', ') : <span className="mx-pipe-muted">none</span>}</dd>
          <dt>Attempts</dt>
          <dd>{row.dispatch.attempts}</dd>
          <dt>Enrolled</dt>
          <dd>{formatLocalDateTime(row.dispatch.createdAt)}</dd>
          <dt>Updated</dt>
          <dd>{formatLocalDateTime(row.dispatch.updatedAt)}</dd>
          {row.prSyncedAt && (
            <>
              <dt>PR data</dt>
              <dd>{formatLocalDateTime(row.prSyncedAt)}</dd>
            </>
          )}
        </dl>
      </section>

      {auditViewerId !== null && (
        <AuditViewer auditId={auditViewerId} onClose={() => setAuditViewerId(null)} />
      )}
      {showVerdict && review && (
        <VerdictModal
          mode="review"
          reviewId={review.reviewId}
          prNumber={row.prNumber}
          repo={row.repo}
          onClose={() => setShowVerdict(false)}
          onRefresh={refresh}
        />
      )}
      {showNotes && (
        <NotesModal
          prNumber={row.prNumber}
          repo={row.repo}
          onClose={() => setShowNotes(false)}
          onUpdate={refresh}
        />
      )}
      {showDescription && (
        <QueueDescriptionModal
          owner={owner}
          repo={repoName}
          prNumber={row.prNumber}
          prTitle={title}
          isOpen={showDescription}
          onClose={() => setShowDescription(false)}
        />
      )}
      {overrideOpen && (
        <AutoVerdictConfigModal
          onClose={() => setOverrideOpen(false)}
          perPR={{
            prNumber: row.prNumber,
            repo: row.repo,
            override: row.autoVerdict?.criteriaOverride ?? null,
            onSaved: (saved) => {
              setCriteriaLocal(row.repo, row.prNumber, saved)
              refresh()
            },
          }}
        />
      )}
    </div>
  )
}
