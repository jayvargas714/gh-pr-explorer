import { useEffect, useState } from 'react'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import { ReviewComparison } from './ReviewComparison'
import { PublishPreview } from './PublishPreview'
import { FindingCard } from './FindingCard'
import { useWorkflowEngineStore } from '../../stores/useWorkflowEngineStore'
import type { WorkflowInstance, WorkflowArtifact } from '../../api/workflow-engine'

type GateTab = 'overview' | 'comparison' | 'publish' | 'freshness'

interface GateViewProps {
  instance: WorkflowInstance
  onBack: () => void
}

interface ParsedContent {
  [key: string]: unknown
}

function parseContent(artifact: WorkflowArtifact): ParsedContent | null {
  const raw = artifact.content_json
  if (!raw) return null
  if (typeof raw === 'string') {
    try { return JSON.parse(raw) } catch { return null }
  }
  return raw as ParsedContent
}

export function GateView({ instance, onBack }: GateViewProps) {
  const { selectedInstance, fetchInstance, approveGate, rejectGate, loading } = useWorkflowEngineStore()
  const [tab, setTab] = useState<GateTab>('overview')
  const [rejectReason, setRejectReason] = useState('')
  const [showRejectForm, setShowRejectForm] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const inst = selectedInstance ?? instance

  useEffect(() => {
    fetchInstance(instance.id)
  }, [instance.id, fetchInstance])

  const artifacts = inst.artifacts ?? []
  const steps = inst.steps ?? []

  const synthArtifact = artifacts.find((a) => a.artifact_type === 'synthesis')
  const synthContent = synthArtifact ? parseContent(synthArtifact) : null

  const freshnessArtifact = artifacts.find(
    (a) => a.artifact_type === 'freshness' || a.step_id.includes('freshness')
  )
  const freshnessContent = freshnessArtifact ? parseContent(freshnessArtifact) : null
  const freshnessChecks = (freshnessContent?.checks ?? freshnessContent?.results ?? []) as Array<{
    pr_number?: number; status?: string; head_sha?: string; reviewed_sha?: string
  }>

  const reviewArtifacts = artifacts.filter(
    (a) => a.artifact_type === 'review' || a.artifact_type === 'review_json'
  )

  const gateStep = steps.find((s) => s.step_type === 'human_gate')
  const isResolved = gateStep?.status === 'completed'

  const verdict = synthContent?.verdict as string | undefined
  const agreed = (synthContent?.agreed ?? []) as Array<Record<string, unknown>>
  const aOnly = ((synthContent?.a_only ?? synthContent?.['A-ONLY'] ?? []) as Array<Record<string, unknown>>)
  const bOnly = ((synthContent?.b_only ?? synthContent?.['B-ONLY'] ?? []) as Array<Record<string, unknown>>)
  const totalFindings = agreed.length + aOnly.length + bOnly.length
  const agreementRate = totalFindings > 0 ? Math.round((agreed.length / totalFindings) * 100) : 0

  const handleApprove = async () => {
    setSubmitting(true)
    await approveGate(inst.id)
    setSubmitting(false)
    onBack()
  }

  const handleReject = async () => {
    if (!rejectReason.trim()) return
    setSubmitting(true)
    await rejectGate(inst.id, { reason: rejectReason.trim() })
    setSubmitting(false)
    onBack()
  }

  const tabs: { id: GateTab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'comparison', label: 'Comparison' },
    { id: 'publish', label: 'Publish Preview' },
    { id: 'freshness', label: 'Freshness' },
  ]

  return (
    <div className="mx-gate-view">
      <div className="mx-gate-view__header">
        <Button variant="ghost" size="sm" onClick={onBack}>&larr; Back to Run</Button>
        <div className="mx-gate-view__title">
          <h3>Review Gate — Run #{inst.id}</h3>
          <Badge variant={isResolved ? 'success' : 'warning'}>{isResolved ? 'Resolved' : 'Awaiting Decision'}</Badge>
        </div>
      </div>

      <div className="mx-gate-view__stats">
        <div className="mx-gate-view__stat">
          <span className="mx-gate-view__stat-value">{verdict ?? '—'}</span>
          <span className="mx-gate-view__stat-label">Verdict</span>
        </div>
        <div className="mx-gate-view__stat">
          <span className="mx-gate-view__stat-value mx-gate-view__stat-value--agreed">{agreed.length}</span>
          <span className="mx-gate-view__stat-label">Agreed</span>
        </div>
        <div className="mx-gate-view__stat">
          <span className="mx-gate-view__stat-value mx-gate-view__stat-value--disputed">{aOnly.length + bOnly.length}</span>
          <span className="mx-gate-view__stat-label">Disputed</span>
        </div>
        <div className="mx-gate-view__stat">
          <span className="mx-gate-view__stat-value">{totalFindings}</span>
          <span className="mx-gate-view__stat-label">Total Findings</span>
        </div>
        <div className="mx-gate-view__stat">
          <span className="mx-gate-view__stat-value">{agreementRate}%</span>
          <span className="mx-gate-view__stat-label">Agreement</span>
        </div>
      </div>

      <div className="mx-gate-view__tabs">
        {tabs.map((t) => (
          <button
            key={t.id}
            className={`mx-gate-view__tab ${tab === t.id ? 'mx-gate-view__tab--active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="mx-gate-view__body">
        {tab === 'overview' && (
          <div className="mx-gate-view__overview">
            {Boolean(synthContent?.summary) && (
              <div className="mx-gate-view__section">
                <h4>Summary</h4>
                <p>{String(synthContent!.summary)}</p>
              </div>
            )}

            {agreed.length > 0 && (
              <div className="mx-gate-view__section">
                <h4>
                  <Badge variant="success" size="sm">Agreed</Badge>
                  <span>{agreed.length} findings</span>
                </h4>
                {agreed.map((f, i) => (
                  <FindingCard key={i} finding={f as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} classification="AGREED" />
                ))}
              </div>
            )}

            {aOnly.length > 0 && (
              <div className="mx-gate-view__section">
                <h4>
                  <Badge variant="warning" size="sm">A-Only</Badge>
                  <span>{aOnly.length} findings</span>
                </h4>
                {aOnly.map((f, i) => (
                  <FindingCard key={i} finding={f as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} classification="A-ONLY" />
                ))}
              </div>
            )}

            {bOnly.length > 0 && (
              <div className="mx-gate-view__section">
                <h4>
                  <Badge variant="warning" size="sm">B-Only</Badge>
                  <span>{bOnly.length} findings</span>
                </h4>
                {bOnly.map((f, i) => (
                  <FindingCard key={i} finding={f as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} classification="B-ONLY" />
                ))}
              </div>
            )}

            {totalFindings === 0 && !synthContent?.summary && (
              <p className="mx-gate-view__empty">No synthesis data available yet.</p>
            )}
          </div>
        )}

        {tab === 'comparison' && (
          <ReviewComparison artifacts={reviewArtifacts} synthesisArtifact={synthArtifact} />
        )}

        {tab === 'publish' && <PublishPreview artifacts={artifacts} />}

        {tab === 'freshness' && (
          <div className="mx-gate-view__freshness">
            {freshnessChecks.length === 0 ? (
              <p className="mx-gate-view__empty">No freshness data available.</p>
            ) : (
              <div className="mx-gate-view__freshness-grid">
                {freshnessChecks.map((c, i) => (
                  <div key={i} className="mx-gate-view__freshness-card">
                    <div className="mx-gate-view__freshness-pr">PR #{c.pr_number}</div>
                    <Badge
                      variant={c.status === 'CURRENT' ? 'success' : c.status === 'STALE-MINOR' ? 'warning' : 'error'}
                    >
                      {c.status ?? 'UNKNOWN'}
                    </Badge>
                    {c.head_sha && (
                      <div className="mx-gate-view__freshness-sha">
                        <span>HEAD:</span> <code>{c.head_sha.slice(0, 8)}</code>
                      </div>
                    )}
                    {c.reviewed_sha && (
                      <div className="mx-gate-view__freshness-sha">
                        <span>Reviewed:</span> <code>{c.reviewed_sha.slice(0, 8)}</code>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {!isResolved && (
        <div className="mx-gate-view__actions">
          {!showRejectForm ? (
            <>
              <Button
                variant="primary"
                onClick={handleApprove}
                disabled={submitting || loading}
              >
                {submitting ? <Spinner size="sm" /> : 'Approve & Continue'}
              </Button>
              <Button
                variant="danger"
                onClick={() => setShowRejectForm(true)}
                disabled={submitting || loading}
              >
                Reject
              </Button>
            </>
          ) : (
            <div className="mx-gate-view__reject-form">
              <textarea
                className="mx-gate-view__reject-textarea"
                placeholder="Reason for rejection (required)..."
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                rows={3}
              />
              <div className="mx-gate-view__reject-btns">
                <Button
                  variant="danger"
                  onClick={handleReject}
                  disabled={!rejectReason.trim() || submitting}
                >
                  {submitting ? <Spinner size="sm" /> : 'Confirm Reject'}
                </Button>
                <Button variant="ghost" onClick={() => setShowRejectForm(false)}>Cancel</Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
