import { useEffect, useState } from 'react'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import { listFollowups, type ReviewFollowup, type FollowupFinding } from '../../api/workflow-engine'

interface FollowUpTrackerProps {
  repo: string
  onClose: () => void
}

const STATUS_VARIANT: Record<string, 'success' | 'warning' | 'error' | 'info' | 'neutral'> = {
  NO_RESPONSE: 'neutral',
  DISCUSSING: 'info',
  PARTIALLY_RESOLVED: 'warning',
  AUTHOR_DISAGREES: 'error',
  RESOLVED: 'success',
  CONCEDED: 'success',
  MERGED: 'success',
  CLOSED: 'neutral',
  WONTFIX: 'neutral',
}

const FINDING_STATUS_VARIANT: Record<string, 'success' | 'warning' | 'error' | 'neutral'> = {
  OPEN: 'error',
  RESOLVED: 'success',
  AUTHOR_DISAGREES: 'warning',
  CONCEDED: 'neutral',
  SUPERSEDED: 'neutral',
}

export function FollowUpTracker({ repo, onClose }: FollowUpTrackerProps) {
  const [followups, setFollowups] = useState<ReviewFollowup[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const refresh = async () => {
    setLoading(true)
    try {
      const data = await listFollowups(repo || undefined)
      setFollowups(data)
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => { refresh() }, [repo])

  if (loading) return <div className="mx-followup"><Spinner /> Loading follow-ups...</div>

  return (
    <div className="mx-followup">
      <div className="mx-followup__header">
        <h3>Follow-Up Tracker</h3>
        <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
      </div>

      {followups.length === 0 ? (
        <p className="mx-followup__empty">No follow-ups yet. Published reviews with blocking findings will appear here.</p>
      ) : (
        <div className="mx-followup__list">
          {followups.map(fu => {
            const isOpen = expandedId === fu.id
            return (
              <div key={fu.id} className="mx-followup__item">
                <div className="mx-followup__item-header" onClick={() => setExpandedId(isOpen ? null : fu.id)}>
                  <span className="mx-followup__toggle">{isOpen ? '▼' : '▶'}</span>
                  <span className="mx-followup__pr">PR #{fu.pr_number}</span>
                  <code className="mx-followup__repo">{fu.repo}</code>
                  <Badge variant={STATUS_VARIANT[fu.status] ?? 'neutral'} size="sm">{fu.status}</Badge>
                  <Badge variant={fu.verdict === 'CHANGES_REQUESTED' ? 'error' : fu.verdict === 'NEEDS_DISCUSSION' ? 'warning' : 'info'} size="sm">
                    {fu.verdict}
                  </Badge>
                  {fu.published_at && (
                    <span className="mx-followup__date">
                      {new Date(fu.published_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
                {isOpen && (
                  <div className="mx-followup__detail">
                    <div className="mx-followup__meta">
                      <span>Source Run: #{fu.source_run_id}</span>
                      {fu.review_sha && <span>SHA: <code>{fu.review_sha.slice(0, 8)}</code></span>}
                      {fu.last_checked && <span>Last checked: {new Date(fu.last_checked).toLocaleString()}</span>}
                      {fu.notes && <p className="mx-followup__notes">{fu.notes}</p>}
                    </div>
                    {fu.findings && fu.findings.length > 0 && (
                      <div className="mx-followup__findings">
                        <h5>Findings ({fu.findings.length})</h5>
                        {fu.findings.map((f: FollowupFinding) => (
                          <div key={f.id} className="mx-followup__finding">
                            <Badge variant={FINDING_STATUS_VARIANT[f.status] ?? 'neutral'} size="sm">
                              {f.status}
                            </Badge>
                            <strong>{f.finding_id}</strong>
                            <Badge variant={f.severity === 'critical' ? 'error' : f.severity === 'major' ? 'warning' : 'neutral'} size="sm">
                              {f.severity}
                            </Badge>
                            <span>{f.original_text}</span>
                            {f.author_response && (
                              <p className="mx-followup__response">Author: {f.author_response}</p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
