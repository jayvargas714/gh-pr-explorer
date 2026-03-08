import { useEffect, useState } from 'react'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import { ReviewComparison } from './ReviewComparison'
import { PublishPreview } from './PublishPreview'
import { FindingCard } from './FindingCard'
import { useWorkflowEngineStore } from '../../stores/useWorkflowEngineStore'
import type { WorkflowInstance, WorkflowArtifact } from '../../api/workflow-engine'

type GateTab = 'overview' | 'comparison' | 'publish' | 'freshness' | 'synthesis_log' | 'questions' | 'domains'

interface GateViewProps {
  instance: WorkflowInstance
  onBack: () => void
}

interface ParsedContent {
  [key: string]: unknown
}

const VERDICT_VARIANT: Record<string, 'success' | 'warning' | 'error' | 'info' | 'neutral'> = {
  APPROVE: 'success',
  CHANGES_REQUESTED: 'error',
  NEEDS_DISCUSSION: 'warning',
  COMMENT: 'info',
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
    pr_number?: number; classification?: string; review_sha?: string; current_sha?: string
    affected_findings?: string[]; recommendation?: string
  }>

  const reviewArtifacts = artifacts.filter(
    (a) => a.artifact_type === 'review' || a.artifact_type === 'review_json'
  )

  const gateStep = steps.find((s) => s.step_type === 'human_gate')
  const isResolved = gateStep?.status === 'completed'

  const gateOutputs = (() => {
    if (!gateStep?.outputs_json) return null
    try {
      const raw = gateStep.outputs_json
      return typeof raw === 'string' ? JSON.parse(raw) : raw
    } catch { return null }
  })()

  const verdict = synthContent?.verdict as string | undefined
  const agreed = (synthContent?.agreed ?? []) as Array<Record<string, unknown>>
  const aOnly = ((synthContent?.a_only ?? synthContent?.['A-ONLY'] ?? []) as Array<Record<string, unknown>>)
  const bOnly = ((synthContent?.b_only ?? synthContent?.['B-ONLY'] ?? []) as Array<Record<string, unknown>>)
  const totalFindings = agreed.length + aOnly.length + bOnly.length
  const agreementRate = totalFindings > 0 ? Math.round((agreed.length / totalFindings) * 100) : 0

  const synthesisLog = (gateOutputs?.synthesis_log ?? synthContent?.synthesis_log ?? []) as Array<{
    type?: string; finding_source?: string; agent?: string; finding?: Record<string, unknown>
    resolution?: string; evidence?: string
  }>
  const questions = (gateOutputs?.questions ?? synthContent?.questions ?? []) as string[]
  const perDomainSynthesis = (gateOutputs?.per_domain_synthesis ?? synthContent?.per_domain_synthesis ?? []) as Array<{
    domain?: string; verdict?: string; total_findings?: number; agent_a?: string; agent_b?: string
    agreed?: Array<Record<string, unknown>>; a_only?: Array<Record<string, unknown>>; b_only?: Array<Record<string, unknown>>
  }>

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

  const tabs: { id: GateTab; label: string; show: boolean }[] = [
    { id: 'overview', label: 'Overview', show: true },
    { id: 'comparison', label: 'Comparison', show: true },
    { id: 'synthesis_log', label: `Synthesis Log (${synthesisLog.length})`, show: synthesisLog.length > 0 },
    { id: 'questions', label: `Questions (${questions.length})`, show: questions.length > 0 },
    { id: 'domains', label: `Domains (${perDomainSynthesis.length})`, show: perDomainSynthesis.length > 0 },
    { id: 'publish', label: 'Publish Preview', show: true },
    { id: 'freshness', label: 'Freshness', show: true },
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
          <span className="mx-gate-view__stat-value">
            <Badge variant={VERDICT_VARIANT[verdict ?? ''] ?? 'neutral'}>{verdict ?? '—'}</Badge>
          </span>
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
        {tabs.filter(t => t.show).map((t) => (
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
                  <FindingCard key={i} finding={f as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} source="BOTH" classification="AGREED" />
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
                  <FindingCard key={i} finding={f as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} source="A" classification="A-ONLY" />
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
                  <FindingCard key={i} finding={f as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} source="B" classification="B-ONLY" />
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

        {tab === 'synthesis_log' && (
          <div className="mx-gate-view__synthesis-log">
            {synthesisLog.length === 0 ? (
              <p className="mx-gate-view__empty">No synthesis log entries.</p>
            ) : (
              synthesisLog.map((entry, i) => (
                <div key={i} className="mx-gate-view__log-entry">
                  <div className="mx-gate-view__log-header">
                    <Badge variant={entry.type === 'disagreement' ? 'warning' : 'info'} size="sm">
                      {entry.finding_source ?? entry.type}
                    </Badge>
                    {entry.agent && <Badge variant="neutral" size="sm">{entry.agent}</Badge>}
                  </div>
                  <div className="mx-gate-view__log-body">
                    <strong>{(entry.finding as Record<string, unknown>)?.title as string ?? 'Finding'}</strong>
                    <p>{entry.resolution}</p>
                    {entry.evidence && <code className="mx-gate-view__log-evidence">{entry.evidence}</code>}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {tab === 'questions' && (
          <div className="mx-gate-view__questions">
            {questions.length === 0 ? (
              <p className="mx-gate-view__empty">No questions from reviewers.</p>
            ) : (
              <ol className="mx-gate-view__question-list">
                {questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ol>
            )}
          </div>
        )}

        {tab === 'domains' && (
          <div className="mx-gate-view__domains">
            {perDomainSynthesis.length === 0 ? (
              <p className="mx-gate-view__empty">No per-domain synthesis data.</p>
            ) : (
              <div className="mx-gate-view__domain-grid">
                {perDomainSynthesis.map((ds, i) => (
                  <div key={i} className="mx-gate-view__domain-card">
                    <div className="mx-gate-view__domain-header">
                      <Badge variant="info" size="sm">{ds.domain ?? 'general'}</Badge>
                      <Badge variant={VERDICT_VARIANT[ds.verdict ?? ''] ?? 'neutral'} size="sm">
                        {ds.verdict ?? 'COMMENT'}
                      </Badge>
                      <span>{ds.total_findings ?? 0} findings</span>
                    </div>
                    <div className="mx-gate-view__domain-agents">
                      {ds.agent_a && <span>A: {ds.agent_a}</span>}
                      {ds.agent_b && <span>B: {ds.agent_b}</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {tab === 'publish' && <PublishPreview artifacts={artifacts} />}

        {tab === 'freshness' && (
          <div className="mx-gate-view__freshness">
            {freshnessChecks.length === 0 ? (
              <p className="mx-gate-view__empty">No freshness data available.</p>
            ) : (
              <div className="mx-gate-view__freshness-grid">
                {freshnessChecks.map((c, i) => {
                  const cls = c.classification ?? 'UNKNOWN'
                  const variant = cls === 'CURRENT' ? 'success'
                    : cls === 'STALE-MINOR' ? 'warning'
                    : cls === 'SUPERSEDED' ? 'error'
                    : cls === 'STALE-MAJOR' ? 'error' : 'neutral'
                  return (
                    <div key={i} className="mx-gate-view__freshness-card">
                      <div className="mx-gate-view__freshness-pr">PR #{c.pr_number}</div>
                      <Badge variant={variant}>{cls}</Badge>
                      {c.review_sha && (
                        <div className="mx-gate-view__freshness-sha">
                          <span>Reviewed:</span> <code>{c.review_sha.slice(0, 8)}</code>
                        </div>
                      )}
                      {c.current_sha && (
                        <div className="mx-gate-view__freshness-sha">
                          <span>Current:</span> <code>{c.current_sha.slice(0, 8)}</code>
                        </div>
                      )}
                      {c.recommendation && (
                        <p className="mx-gate-view__freshness-rec">{c.recommendation}</p>
                      )}
                      {c.affected_findings && c.affected_findings.length > 0 && (
                        <div className="mx-gate-view__freshness-affected">
                          <strong>Potentially affected:</strong>
                          {c.affected_findings.map((f, j) => (
                            <Badge key={j} variant="warning" size="sm">{f}</Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
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
