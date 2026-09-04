import { useState } from 'react'
import type { PipelineIssueCounts, PipelineRow as PipelineRowData } from '../../api/types'
import { usePipelineStore } from '../../stores/usePipelineStore'
import { useReviewStore } from '../../stores/useReviewStore'
import { useQueueStore } from '../../stores/useQueueStore'
import { addToQueue, fetchMergeQueue, removeFromQueue } from '../../api/queue'
import { refreshPipelineRow } from '../../api/pipeline'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { CIStatusBadge } from '../common/CIStatusBadge'
import { ReviewersBadge } from '../common/ReviewersBadge'
import { AutomationPipelineControl } from '../common/AutomationPipelineControl'
import { AutoVerdictToggle } from '../autoVerdict/AutoVerdictToggle'
import { RevLogBadge } from '../queue/RevLogBadge'
import { AuditViewer } from '../audits/AuditViewer'
import { formatFullDateTime, formatNumber, formatRelativeTime } from '../../utils/formatters'
import { prUrl, stagePresentation } from './pipelineFilters'

interface PipelineRowProps {
  row: PipelineRowData
  selected: boolean
  expanded: boolean
}

function issueTooltip(label: string, c: PipelineIssueCounts): string {
  const parts = [`${label}: ${c.posted ?? '?'}/${c.found ?? '?'} posted`]
  c.titles?.forEach((t, i) => parts.push(`${i + 1}. ${t}`))
  if (c.posted !== null && c.found !== null && c.posted < c.found) {
    parts.push(`⚠ ${c.found - c.posted} not posted (lines not in diff)`)
  }
  return parts.join('\n')
}

function IssueCell({ row }: { row: PipelineRowData }) {
  const r = row.review
  if (!r) return <span className="mx-pipe-muted">—</span>
  const cells: { short: string; label: string; counts: PipelineIssueCounts }[] = [
    { short: 'C', label: 'Critical', counts: r.critical },
    { short: 'M', label: 'Major', counts: r.major },
    { short: 'm', label: 'Minor', counts: r.minor },
  ]
  return (
    <span className="mx-pipe-issues">
      {cells.map(({ short, label, counts }) => {
        const found = counts.found ?? 0
        const underPosted = counts.posted !== null && counts.posted < found
        return (
          <span
            key={short}
            className={
              'mx-pipe-issues__item' +
              (found === 0 ? ' mx-pipe-issues__item--none' : underPosted ? ' mx-pipe-issues__item--short' : '')
            }
            data-tooltip={issueTooltip(label, counts)}
          >
            {short} {counts.posted ?? '?'}/{counts.found ?? '?'}
          </span>
        )
      })}
    </span>
  )
}

function decisionBadge(decision: PipelineRowData['reviewDecision']) {
  switch (decision) {
    case 'APPROVED':
      return <Badge variant="success" size="sm">✓ Approved</Badge>
    case 'CHANGES_REQUESTED':
      return <Badge variant="error" size="sm">✗ Changes</Badge>
    case 'REVIEW_REQUIRED':
      return <Badge variant="warning" size="sm">👀 Required</Badge>
    default:
      return null
  }
}

/** One compact table row. Clicking the row toggles the detail panel; every
 * interactive cell stops propagation so controls don't also expand it. */
export function PipelineRow({ row, selected, expanded }: PipelineRowProps) {
  const toggleSelect = usePipelineStore((s) => s.toggleSelect)
  const toggleExpanded = usePipelineStore((s) => s.toggleExpanded)
  const patchRow = usePipelineStore((s) => s.patchRow)
  const setOnBoardLocal = usePipelineStore((s) => s.setOnBoardLocal)
  const refresh = usePipelineStore((s) => s.refresh)
  const openReviewViewer = useReviewStore((s) => s.openReviewViewer)
  const setMergeQueue = useQueueStore((s) => s.setMergeQueue)

  const [auditViewerId, setAuditViewerId] = useState<number | null>(null)
  const [boardBusy, setBoardBusy] = useState(false)
  const [refreshBusy, setRefreshBusy] = useState(false)

  const stage = stagePresentation(row)
  const stop = (e: React.SyntheticEvent) => e.stopPropagation()

  const handleBoardToggle = async () => {
    if (boardBusy) return
    setBoardBusy(true)
    try {
      if (row.onBoard) {
        await removeFromQueue(row.prNumber, row.repo)
        setOnBoardLocal(row.key, false)
      } else {
        await addToQueue({
          number: row.prNumber,
          title: row.title ?? `#${row.prNumber}`,
          url: prUrl(row),
          author: row.author ?? '',
          repo: row.repo,
          additions: row.additions ?? undefined,
          deletions: row.deletions ?? undefined,
        })
        setOnBoardLocal(row.key, true)
      }
      // Keep the header's queue count honest.
      fetchMergeQueue().then((resp) => setMergeQueue(resp.queue)).catch(() => null)
    } catch (err) {
      console.error('Failed to update board membership:', err)
    } finally {
      setBoardBusy(false)
    }
  }

  const handleRefreshRow = async () => {
    if (refreshBusy) return
    setRefreshBusy(true)
    try {
      const { row: fresh } = await refreshPipelineRow(row.repo, row.prNumber)
      patchRow(fresh)
    } catch (err) {
      console.error('Failed to refresh pipeline row:', err)
    } finally {
      setRefreshBusy(false)
    }
  }

  return (
    <>
      <tr
        className={[
          'mx-pipe-row',
          `mx-pipe-row--${row.stage}`,
          selected ? 'mx-pipe-row--selected' : '',
          expanded ? 'mx-pipe-row--expanded' : '',
          row.running ? 'mx-pipe-row--running' : '',
        ]
          .filter(Boolean)
          .join(' ')}
        onClick={() => toggleExpanded(row.key)}
        data-pr-number={row.prNumber}
      >
        <td className="mx-pipe-table__check" onClick={stop}>
          <input
            type="checkbox"
            checked={selected}
            onChange={() => toggleSelect(row.key)}
            aria-label={`Select ${row.repo}#${row.prNumber}`}
          />
        </td>

        <td className="mx-pipe-table__col-pr">
          <div className="mx-pipe-pr">
            <a
              href={prUrl(row)}
              target="_blank"
              rel="noopener noreferrer"
              className="mx-pipe-pr__link"
              onClick={stop}
            >
              {row.repo}#{row.prNumber}
            </a>
            {row.isDraft && <Badge variant="warning" size="sm">Draft</Badge>}
            {row.reviewRequest?.status === 'pending' && (
              <span data-tooltip={row.reviewRequest.detail ?? 'Follow-up review queued by a GitHub review request'}>
                <Badge variant="info" size="sm">🙋 Follow-up requested</Badge>
              </span>
            )}
            {row.reviewRequestedFromMe && row.reviewRequest?.status !== 'pending' && (
              <span data-tooltip="A review is currently requested from the PR Explorer account on GitHub">
                <Badge variant="info" size="sm">🙋 Review requested</Badge>
              </span>
            )}
            {row.baseRefName && (
              <span className="mx-pipe-pr__base" data-tooltip="Base branch">→ {row.baseRefName}</span>
            )}
          </div>
          <div className="mx-pipe-pr__title" title={row.title ?? undefined}>
            {row.title ?? <span className="mx-pipe-muted">(no synced PR data)</span>}
          </div>
          <div className="mx-pipe-pr__meta">
            {row.author && <span>by {row.author}</span>}
            {row.additions !== null && (
              <span className="mx-stats-additions">+{formatNumber(row.additions)}</span>
            )}
            {row.deletions !== null && (
              <span className="mx-stats-deletions">-{formatNumber(row.deletions)}</span>
            )}
          </div>
        </td>

        <td className="mx-pipe-table__col-stage">
          <span className={`mx-pipe-stage mx-pipe-stage--${row.stage}`}>
            <span className="mx-pipe-stage__icon" aria-hidden="true">{stage.icon}</span>
            <span className="mx-pipe-stage__label">{stage.label}</span>
          </span>
          {stage.reason && (
            <div className="mx-pipe-stage__reason" title={stage.reason}>{stage.reason}</div>
          )}
        </td>

        <td className="mx-pipe-table__col-rounds" onClick={stop}>
          <span className="mx-pipe-rounds-count">{row.rounds}</span>
          <RevLogBadge
            entries={row.revLog}
            onOpenReview={(id) => openReviewViewer({ id })}
            onOpenAudit={setAuditViewerId}
          />
        </td>

        <td className="mx-pipe-table__col-auto" onClick={stop}>
          <AutoVerdictToggle
            repo={row.repo}
            prNumber={row.prNumber}
            autoVerdict={row.autoVerdict}
            onRefresh={refresh}
          />
        </td>

        <td className="mx-pipe-table__col-ci" onClick={stop}>
          {row.ciStatus ? (
            <CIStatusBadge ciStatus={row.ciStatus} statusCheckRollup={row.statusCheckRollup} />
          ) : (
            <span className="mx-pipe-muted">—</span>
          )}
        </td>

        <td className="mx-pipe-table__col-review" onClick={stop}>
          <div className="mx-pipe-badges">
            {decisionBadge(row.reviewDecision)}
            {row.currentReviewers.length > 0 && <ReviewersBadge reviewers={row.currentReviewers} />}
            {!row.reviewDecision && row.currentReviewers.length === 0 && (
              <span className="mx-pipe-muted">—</span>
            )}
          </div>
        </td>

        <td className="mx-pipe-table__col-issues">
          <IssueCell row={row} />
        </td>

        <td className="mx-pipe-table__col-updated">
          {row.prUpdatedAt ? (
            <span title={formatFullDateTime(row.prUpdatedAt)}>{formatRelativeTime(row.prUpdatedAt)}</span>
          ) : (
            <span className="mx-pipe-muted">—</span>
          )}
        </td>

        <td className="mx-pipe-table__col-actions" onClick={stop}>
          <div className="mx-pipe-actions">
            <AutomationPipelineControl
              repo={row.repo}
              prNumber={row.prNumber}
              automation={row.automation ?? row.dispatch}
              prState={row.prState ?? undefined}
            />
            <Button
              variant="ghost"
              size="sm"
              onClick={handleBoardToggle}
              disabled={boardBusy}
              className={row.onBoard ? 'mx-pipe-board-btn mx-pipe-board-btn--on' : 'mx-pipe-board-btn'}
              data-tooltip={row.onBoard ? 'Remove from the swimlane board' : 'Watch on the swimlane board'}
              aria-pressed={row.onBoard}
            >
              📋{row.onBoard ? ' ✓' : ''}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleRefreshRow}
              disabled={refreshBusy}
              data-tooltip="Re-fetch this PR from GitHub"
              aria-label="Refresh row"
            >
              {refreshBusy ? '…' : '↻'}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => toggleExpanded(row.key)}
              data-tooltip={expanded ? 'Collapse' : 'Expand'}
              aria-expanded={expanded}
              aria-label={expanded ? 'Collapse row' : 'Expand row'}
            >
              {expanded ? '▾' : '▸'}
            </Button>
          </div>
        </td>
      </tr>

      {auditViewerId !== null && (
        <AuditViewer auditId={auditViewerId} onClose={() => setAuditViewerId(null)} />
      )}
    </>
  )
}
