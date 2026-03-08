import { useEffect, useState } from 'react'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import { FindingCard } from './FindingCard'
import { useWorkflowEngineStore } from '../../stores/useWorkflowEngineStore'
import type { WorkflowInstance } from '../../api/workflow-engine'

type GateTab = 'overview' | 'comparison' | 'publish' | 'freshness' | 'synthesis_log' | 'questions' | 'domains'

interface GateViewProps {
  instance: WorkflowInstance
  onBack: () => void
}

const VERDICT_VARIANT: Record<string, 'success' | 'warning' | 'error' | 'info' | 'neutral'> = {
  APPROVE: 'success',
  CHANGES_REQUESTED: 'error',
  NEEDS_DISCUSSION: 'warning',
  COMMENT: 'info',
}


function PromptReviewGate({ instance, gateOutputs, onBack }: {
  instance: WorkflowInstance
  gateOutputs: Record<string, unknown>
  onBack: () => void
}) {
  const { approveGate, rejectGate, reviseGate, loading } = useWorkflowEngineStore()
  const payload = (gateOutputs?.gate_payload ?? gateOutputs) as Record<string, unknown>
  const initialPrompts = (payload.prompts ?? []) as Array<{
    pr_number?: number; pr_title?: string; domain?: string; prompt?: string; [key: string]: unknown
  }>
  const experts = (payload.experts ?? []) as Array<{
    domain_id?: string; display_name?: string; persona?: string; scope?: string
  }>
  const mode = payload.mode as string | undefined

  const expertSource = payload.expert_source as string | undefined
  const domainCount = (payload.domain_count ?? 0) as number
  const promptsPerPr = (payload.prompts_per_pr ?? 0) as number
  const feedbackHistory = (payload.feedback_history ?? []) as Array<{ feedback?: string; iteration?: number }>
  const iteration = (payload.iteration ?? 1) as number

  const [editedPrompts, setEditedPrompts] = useState(initialPrompts.map(p => ({ ...p, enabled: true, editedText: p.prompt ?? '' })))
  const [submitting, setSubmitting] = useState(false)
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)
  const [showReviseForm, setShowReviseForm] = useState(false)
  const [reviseFeedback, setReviseFeedback] = useState('')
  const [showFeedbackHistory, setShowFeedbackHistory] = useState(false)

  const handleToggle = (idx: number) => {
    setEditedPrompts(prev => prev.map((p, i) => i === idx ? { ...p, enabled: !p.enabled } : p))
  }

  const handleEdit = (idx: number, text: string) => {
    setEditedPrompts(prev => prev.map((p, i) => i === idx ? { ...p, editedText: text } : p))
  }

  const hasEdits = editedPrompts.some((p, i) => p.editedText !== (initialPrompts[i]?.prompt ?? ''))

  const handleApprove = async () => {
    setSubmitting(true)
    const finalPrompts = editedPrompts
      .filter(p => p.enabled)
      .map(p => ({ ...p, prompt: p.editedText }))
    await approveGate(instance.id, { prompts: finalPrompts })
    setSubmitting(false)
    onBack()
  }

  const handleRevise = async () => {
    if (!reviseFeedback.trim()) return
    if (hasEdits && !confirm('Revising will regenerate all experts and prompts. Your edits will be lost. Continue?')) return
    setSubmitting(true)
    await reviseGate(instance.id, reviseFeedback.trim())
    setSubmitting(false)
    onBack()
  }

  const handleCancel = async () => {
    if (!confirm('This will permanently cancel the workflow. Continue?')) return
    setSubmitting(true)
    await rejectGate(instance.id, { reason: 'Cancelled by user' })
    setSubmitting(false)
    onBack()
  }

  const enabledCount = editedPrompts.filter(p => p.enabled).length

  return (
    <div className="mx-gate-view">
      <div className="mx-gate-view__header">
        <Button variant="ghost" size="sm" onClick={onBack}>&larr; Back to Run</Button>
        <div className="mx-gate-view__title">
          <h3>Prompt Review Gate — Run #{instance.id}</h3>
          <Badge variant="warning">Awaiting Prompt Review</Badge>
          {iteration > 1 && <Badge variant="info" size="sm">Iteration {iteration}</Badge>}
        </div>
      </div>

      {feedbackHistory.length > 0 && (
        <div className="mx-gate-view__feedback-history">
          <button
            className="mx-gate-view__feedback-toggle"
            onClick={() => setShowFeedbackHistory(!showFeedbackHistory)}
          >
            Previous Feedback ({feedbackHistory.length}) {showFeedbackHistory ? '▾' : '▸'}
          </button>
          {showFeedbackHistory && (
            <div className="mx-gate-view__feedback-list">
              {feedbackHistory.map((fb, i) => (
                <div key={i} className="mx-gate-view__feedback-entry">
                  <Badge variant="neutral" size="sm">Iteration {fb.iteration}</Badge>
                  <span>{fb.feedback}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="mx-gate-view__stats">
        <div className="mx-gate-view__stat">
          <span className="mx-gate-view__stat-value">{editedPrompts.length}</span>
          <span className="mx-gate-view__stat-label">Total Prompts</span>
        </div>
        <div className="mx-gate-view__stat">
          <span className="mx-gate-view__stat-value">{enabledCount}</span>
          <span className="mx-gate-view__stat-label">Enabled</span>
        </div>
        <div className="mx-gate-view__stat">
          <span className="mx-gate-view__stat-value">{domainCount || experts.length}</span>
          <span className="mx-gate-view__stat-label">Expert Domains</span>
        </div>
        {mode && (
          <div className="mx-gate-view__stat">
            <span className="mx-gate-view__stat-value">{mode}</span>
            <span className="mx-gate-view__stat-label">Mode</span>
          </div>
        )}
        <div className="mx-gate-view__stat">
          <span className="mx-gate-view__stat-value">
            <Badge variant={expertSource === 'ai_generated' ? 'success' : expertSource === 'static_match' ? 'warning' : 'neutral'} size="sm">
              {expertSource === 'ai_generated' ? 'AI Generated' : expertSource === 'static_match' ? 'Static Match' : 'Unknown'}
            </Badge>
          </span>
          <span className="mx-gate-view__stat-label">Expert Source</span>
        </div>
        {promptsPerPr > 0 && (
          <div className="mx-gate-view__stat">
            <span className="mx-gate-view__stat-value">{promptsPerPr}</span>
            <span className="mx-gate-view__stat-label">Prompts / PR</span>
          </div>
        )}
      </div>

      {domainCount <= 1 && mode && mode !== 'team-review' && (
        <div style={{ padding: '10px 14px', background: 'rgba(255, 170, 0, 0.1)', border: '1px solid rgba(255, 170, 0, 0.3)', borderRadius: '6px', marginBottom: '12px', fontSize: '13px' }}>
          <strong>Warning:</strong> Only {domainCount || 1} expert domain was selected. For {mode}, 2-4 diverse domains produce better adversarial coverage.
          {expertSource !== 'ai_generated' && ' AI expert generation may have failed — check server logs.'}
        </div>
      )}

      {experts.length > 0 && (
        <div className="mx-gate-view__section" style={{ marginBottom: '16px' }}>
          <h4>Expert Domains</h4>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            {experts.map((e, i) => (
              <div key={i} style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.05)', borderRadius: '6px' }}>
                <Badge variant="info" size="sm">{e.display_name ?? e.domain_id}</Badge>
                {e.scope && <p style={{ margin: '4px 0 0', fontSize: '12px', opacity: 0.7 }}>{e.scope}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mx-gate-view__body">
        {editedPrompts.map((p, i) => {
          const isOpen = expandedIdx === i
          return (
            <div key={i} className="mx-gate-view__section" style={{
              opacity: p.enabled ? 1 : 0.5,
              borderLeft: p.enabled ? '3px solid var(--mx-accent)' : '3px solid transparent',
              paddingLeft: '12px',
              marginBottom: '12px',
            }}>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', cursor: 'pointer' }} onClick={() => setExpandedIdx(isOpen ? null : i)}>
                <input
                  type="checkbox"
                  checked={p.enabled}
                  onChange={(e) => { e.stopPropagation(); handleToggle(i) }}
                  style={{ marginRight: '4px' }}
                />
                <span style={{ fontSize: '12px', opacity: 0.6 }}>{isOpen ? '▼' : '▶'}</span>
                {p.pr_number && <strong>#{p.pr_number}</strong>}
                {p.domain && <Badge variant="info" size="sm">
                  {(p as Record<string, unknown>).domain_display_name as string
                    ?? experts.find(e => e.domain_id === p.domain)?.display_name
                    ?? p.domain}
                </Badge>}
                {p.pr_title && <span style={{ fontSize: '13px', opacity: 0.8 }}>{p.pr_title}</span>}
              </div>
              {isOpen && (
                <div style={{ marginTop: '8px' }}>
                  <textarea
                    value={p.editedText}
                    onChange={(e) => handleEdit(i, e.target.value)}
                    className="mx-gate-view__reject-textarea"
                    style={{ width: '100%', minHeight: '200px', fontFamily: 'monospace', fontSize: '12px' }}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="mx-gate-view__actions">
        {!showReviseForm ? (
          <>
            <Button
              variant="primary"
              onClick={handleApprove}
              disabled={submitting || loading || enabledCount === 0}
            >
              {submitting ? <Spinner size="sm" /> : `Approve & Run Agents (${enabledCount} prompts)`}
            </Button>
            <Button
              variant="warning"
              onClick={() => setShowReviseForm(true)}
              disabled={submitting || loading}
            >
              Revise
            </Button>
            <button
              className="mx-gate-view__cancel-link"
              onClick={handleCancel}
              disabled={submitting || loading}
            >
              Cancel Workflow
            </button>
          </>
        ) : (
          <div className="mx-gate-view__revise-form">
            <textarea
              className="mx-gate-view__reject-textarea"
              placeholder="Describe what should change (e.g., &quot;add an expert for aerodynamic simulation code&quot;, &quot;prompts should emphasize thread safety&quot;)..."
              value={reviseFeedback}
              onChange={(e) => setReviseFeedback(e.target.value)}
              rows={3}
            />
            <div className="mx-gate-view__reject-btns">
              <Button
                variant="warning"
                onClick={handleRevise}
                disabled={!reviseFeedback.trim() || submitting}
              >
                {submitting ? <Spinner size="sm" /> : 'Revise & Regenerate'}
              </Button>
              <Button variant="ghost" onClick={() => setShowReviseForm(false)}>Back</Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function PublishPreviewFromGate({ holisticData, synthData, reviews }: {
  holisticData: Record<string, unknown>
  synthData: Record<string, unknown>
  reviews: Array<{ pr_number?: number; domain?: string; agent_name?: string; score?: number; content_md?: string }>
}) {
  const verdict = (holisticData.verdict ?? synthData.verdict ?? 'COMMENT') as string
  const summary = (holisticData.summary ?? '') as string
  const blocking = (holisticData.blocking_findings ?? []) as Array<Record<string, unknown>>
  const nonBlocking = (holisticData.non_blocking_findings ?? []) as Array<Record<string, unknown>>
  const crossCutting = (holisticData.cross_cutting_findings ?? []) as Array<Record<string, unknown>>
  const agreed = (synthData.agreed ?? []) as Array<Record<string, unknown>>
  const totalFindings = Number(synthData.total_findings ?? 0)
  const domains = (holisticData.domain_coverage ?? []) as string[]

  const lines: string[] = []
  lines.push(`## Adversarial Code Review — ${verdict}\n`)
  if (summary) lines.push(`${summary}\n`)
  lines.push(`**${totalFindings}** findings across **${domains.length}** domains | **${blocking.length}** blocking | **${agreed.length}** agreed by both agents\n`)

  if (blocking.length > 0) {
    lines.push(`### Blocking Findings (${blocking.length})\n`)
    blocking.forEach((f, i) => {
      const title = (f.title ?? 'Untitled') as string
      const severity = (f.severity ?? '') as string
      const domain = (f.domain ?? '') as string
      const desc = (f.description ?? '') as string
      lines.push(`${i + 1}. **[${severity}]** ${title}${domain ? ` _(${domain})_` : ''}`)
      if (desc) lines.push(`   ${desc.slice(0, 200)}${desc.length > 200 ? '...' : ''}\n`)
    })
  }

  if (nonBlocking.length > 0) {
    lines.push(`### Non-Blocking Findings (${nonBlocking.length})\n`)
    nonBlocking.forEach((f, i) => {
      const title = (f.title ?? 'Untitled') as string
      const severity = (f.severity ?? '') as string
      lines.push(`${i + 1}. **[${severity}]** ${title}`)
    })
    lines.push('')
  }

  if (crossCutting.length > 0) {
    lines.push(`### Cross-Cutting Concerns (${crossCutting.length})\n`)
    crossCutting.forEach((f, i) => {
      const title = (f.title ?? 'Untitled') as string
      lines.push(`${i + 1}. ${title}`)
    })
    lines.push('')
  }

  lines.push(`---\n_Generated by adversarial review (${reviews.length} expert reviews)_`)

  const markdown = lines.join('\n')

  return (
    <div className="mx-gate-view__overview">
      <div className="mx-gate-view__section">
        <h4>GitHub Comment Preview</h4>
        <p style={{ fontSize: '12px', opacity: 0.7, marginBottom: '8px' }}>
          This is approximately what will be posted to the PR when you approve. The publish step may further deduplicate against existing comments.
        </p>
        <pre style={{ whiteSpace: 'pre-wrap', fontSize: '12px', lineHeight: '1.5', padding: '12px', background: 'rgba(255,255,255,0.03)', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.1)', maxHeight: '600px', overflow: 'auto' }}>
          {markdown}
        </pre>
      </div>
    </div>
  )
}

function ComparisonView({ reviews, perDomainSynthesis }: {
  reviews: Array<{ pr_number?: number; domain?: string; agent_name?: string; score?: number; content_md?: string; content_json?: Record<string, unknown> }>
  perDomainSynthesis: Array<{ domain?: string; verdict?: string; total_findings?: number; agent_a?: string; agent_b?: string; agreed?: Array<Record<string, unknown>>; a_only?: Array<Record<string, unknown>>; b_only?: Array<Record<string, unknown>> }>
}) {
  const domains = [...new Set(reviews.map(r => r.domain ?? 'general'))]
  const [activeDomain, setActiveDomain] = useState<string>(domains[0] ?? '')
  const [expandedReview, setExpandedReview] = useState<number | null>(null)

  if (reviews.length === 0) {
    return <p className="mx-gate-view__empty">No review data available for comparison.</p>
  }

  const domainReviews = reviews.filter(r => (r.domain ?? 'general') === activeDomain)
  const domainSynth = perDomainSynthesis.find(ds => ds.domain === activeDomain)

  return (
    <div className="mx-gate-view__overview">
      {domains.length > 1 && (
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '12px' }}>
          {domains.map(d => (
            <button
              key={d}
              className={`mx-gate-view__tab ${activeDomain === d ? 'mx-gate-view__tab--active' : ''}`}
              onClick={() => { setActiveDomain(d); setExpandedReview(null) }}
              style={{ fontSize: '12px', padding: '4px 10px' }}
            >
              {d.split('-').slice(-2).join(' ')}
            </button>
          ))}
        </div>
      )}

      {domainSynth && (
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap' }}>
          <Badge variant={VERDICT_VARIANT[domainSynth.verdict ?? ''] ?? 'neutral'} size="sm">{domainSynth.verdict}</Badge>
          <span style={{ fontSize: '13px' }}>
            {domainSynth.total_findings} findings
            ({(domainSynth.agreed ?? []).length} agreed,
            {(domainSynth.a_only ?? []).length} A-only,
            {(domainSynth.b_only ?? []).length} B-only)
          </span>
        </div>
      )}

      {domainReviews.map((r, i) => {
        const isOpen = expandedReview === i
        const sections = (r.content_json?.sections ?? []) as Array<{ display_name?: string; type?: string; issues?: Array<Record<string, unknown>> }>
        const totalIssues = sections.reduce((acc, s) => acc + ((s.issues ?? []).length), 0)
        const summary = r.content_json?.summary as string ?? ''
        const score = r.content_json?.score as Record<string, unknown> | undefined

        return (
          <div key={i} className="mx-gate-view__section" style={{ marginBottom: '12px' }}>
            <div
              style={{ display: 'flex', gap: '8px', alignItems: 'center', cursor: 'pointer' }}
              onClick={() => setExpandedReview(isOpen ? null : i)}
            >
              <span style={{ fontSize: '12px', opacity: 0.6 }}>{isOpen ? '▼' : '▶'}</span>
              <Badge variant="info" size="sm">{r.agent_name ?? 'unknown'}</Badge>
              {r.score != null && <Badge variant="neutral" size="sm">{r.score}/10</Badge>}
              <span style={{ fontSize: '13px' }}>{totalIssues} issues across {sections.length} sections</span>
            </div>
            {!isOpen && summary && (
              <p style={{ margin: '6px 0 0', fontSize: '13px', opacity: 0.8 }}>{summary.slice(0, 200)}{summary.length > 200 ? '...' : ''}</p>
            )}
            {isOpen && (
              <div style={{ marginTop: '8px' }}>
                {summary && <p style={{ marginBottom: '10px', fontSize: '13px' }}>{summary}</p>}
                {score && (
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '10px' }}>
                    <strong>Score: {String(score.overall ?? '?')}/10</strong>
                    {score.summary ? <span style={{ fontSize: '12px', opacity: 0.7 }}>{String(score.summary)}</span> : null}
                  </div>
                )}
                {sections.map((sec, j) => (
                  <div key={j} style={{ marginBottom: '8px' }}>
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginBottom: '4px' }}>
                      <Badge variant={sec.type === 'critical' ? 'error' : sec.type === 'major' ? 'warning' : 'neutral'} size="sm">
                        {sec.type}
                      </Badge>
                      <strong style={{ fontSize: '13px' }}>{sec.display_name} ({(sec.issues ?? []).length})</strong>
                    </div>
                    {(sec.issues ?? []).map((issue, k) => (
                      <FindingCard
                        key={k}
                        finding={issue as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }}
                      />
                    ))}
                  </div>
                ))}
                {r.content_md && (
                  <details style={{ marginTop: '8px' }}>
                    <summary style={{ cursor: 'pointer', fontSize: '12px', opacity: 0.7 }}>Raw Markdown</summary>
                    <pre style={{ maxHeight: '400px', overflow: 'auto', fontSize: '11px', whiteSpace: 'pre-wrap' }}>{r.content_md}</pre>
                  </details>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export function GateView({ instance, onBack }: GateViewProps) {
  const { selectedInstance, fetchInstance, approveGate, rejectGate, reviseGate, loading } = useWorkflowEngineStore()
  const [tab, setTab] = useState<GateTab>('overview')
  const [reviseFeedback, setReviseFeedback] = useState('')
  const [showReviseForm, setShowReviseForm] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [showFeedbackHistory, setShowFeedbackHistory] = useState(false)

  const inst = selectedInstance ?? instance

  useEffect(() => {
    fetchInstance(instance.id)
  }, [instance.id, fetchInstance])

  const steps = inst.steps ?? []

  const activeGateStep = steps.find((s) => s.step_type === 'human_gate' && s.status === 'awaiting_gate')
    ?? [...steps].reverse().find((s) => s.step_type === 'human_gate')
  const isResolved = activeGateStep?.status === 'completed'

  const gateOutputs = (() => {
    if (!activeGateStep?.outputs_json) return null
    try {
      const raw = activeGateStep.outputs_json
      return typeof raw === 'string' ? JSON.parse(raw) : raw
    } catch { return null }
  })() as Record<string, unknown> | null

  const gatePayload = (gateOutputs?.gate_payload ?? gateOutputs ?? {}) as Record<string, unknown>
  const gateType = (gatePayload?.type ?? gateOutputs?.type) as string | undefined

  if (gateType === 'prompt_review') {
    if (!isResolved) return <PromptReviewGate instance={inst} gateOutputs={gateOutputs!} onBack={onBack} />
    return null
  }

  const unwrapFinding = (f: Record<string, unknown>): Record<string, unknown> => {
    if (f.finding_a && typeof f.finding_a === 'object') return f.finding_a as Record<string, unknown>
    if (f.finding && typeof f.finding === 'object') return f.finding as Record<string, unknown>
    return f
  }

  const synthData = (gateOutputs?.synthesis ?? {}) as Record<string, unknown>
  const holisticData = (gateOutputs?.holistic ?? {}) as Record<string, unknown>

  const verdict = (holisticData.verdict ?? synthData.verdict) as string | undefined
  const agreed = (synthData.agreed ?? []) as Array<Record<string, unknown>>
  const aOnly = ((synthData.a_only ?? synthData['A-ONLY'] ?? []) as Array<Record<string, unknown>>)
  const bOnly = ((synthData.b_only ?? synthData['B-ONLY'] ?? []) as Array<Record<string, unknown>>)
  const totalFindings = agreed.length + aOnly.length + bOnly.length
  const agreementRate = totalFindings > 0 ? Math.round((agreed.length / totalFindings) * 100) : 0

  const synthesisLog = (gateOutputs?.synthesis_log ?? synthData.synthesis_log ?? []) as Array<{
    type?: string; finding_source?: string; agent?: string
    finding?: string | Record<string, unknown>
    action?: string; reasoning?: string
    resolution?: string; evidence?: string
  }>
  const questions = (gateOutputs?.questions ?? synthData.questions ?? []) as string[]
  const perDomainSynthesis = (gateOutputs?.per_domain_synthesis ?? synthData.per_domain_synthesis ?? []) as Array<{
    domain?: string; verdict?: string; total_findings?: number; agent_a?: string; agent_b?: string
    agreed?: Array<Record<string, unknown>>; a_only?: Array<Record<string, unknown>>; b_only?: Array<Record<string, unknown>>
  }>

  const gateReviews = (gateOutputs?.reviews ?? []) as Array<{
    pr_number?: number; domain?: string; agent_name?: string; score?: number
    content_md?: string; content_json?: Record<string, unknown>
  }>

  const freshnessChecks = (gateOutputs?.freshness ?? []) as Array<{
    pr_number?: number; classification?: string; review_sha?: string; current_sha?: string
    affected_findings?: string[]; recommendation?: string
  }>

  const blockingFindings = (holisticData.blocking_findings ?? []) as Array<Record<string, unknown>>
  const nonBlockingFindings = (holisticData.non_blocking_findings ?? []) as Array<Record<string, unknown>>
  const crossCuttingFindings = (holisticData.cross_cutting_findings ?? []) as Array<{ title?: string; domains?: string[]; description?: string; origin?: string }>
  const holisticSummary = holisticData.summary as string | undefined

  const feedbackHistory = (gatePayload.feedback_history ?? []) as Array<{ feedback?: string; iteration?: number }>
  const iteration = (gatePayload.iteration ?? 1) as number

  const handleApprove = async () => {
    setSubmitting(true)
    await approveGate(inst.id)
    setSubmitting(false)
    onBack()
  }

  const handleRevise = async () => {
    if (!reviseFeedback.trim()) return
    setSubmitting(true)
    await reviseGate(inst.id, reviseFeedback.trim())
    setSubmitting(false)
    onBack()
  }

  const handleCancel = async () => {
    if (!confirm('This will permanently cancel the workflow. Continue?')) return
    setSubmitting(true)
    await rejectGate(inst.id, { reason: 'Cancelled by user' })
    setSubmitting(false)
    onBack()
  }

  const tabs: { id: GateTab; label: string; show: boolean }[] = [
    { id: 'overview', label: 'Overview', show: true },
    { id: 'domains', label: `Domains (${perDomainSynthesis.length})`, show: perDomainSynthesis.length > 0 },
    { id: 'comparison', label: 'Comparison', show: true },
    { id: 'synthesis_log', label: `Synthesis Log (${synthesisLog.length})`, show: synthesisLog.length > 0 },
    { id: 'questions', label: `Questions (${questions.length})`, show: questions.length > 0 },
    { id: 'publish', label: 'Publish Preview', show: true },
    { id: 'freshness', label: 'Freshness', show: freshnessChecks.length > 0 },
  ]

  return (
    <div className="mx-gate-view">
      <div className="mx-gate-view__header">
        <Button variant="ghost" size="sm" onClick={onBack}>&larr; Back to Run</Button>
        <div className="mx-gate-view__title">
          <h3>Review Gate — Run #{inst.id}</h3>
          <Badge variant={isResolved ? 'success' : 'warning'}>{isResolved ? 'Resolved' : 'Awaiting Decision'}</Badge>
          {iteration > 1 && <Badge variant="info" size="sm">Iteration {iteration}</Badge>}
        </div>
      </div>

      {feedbackHistory.length > 0 && (
        <div className="mx-gate-view__feedback-history">
          <button
            className="mx-gate-view__feedback-toggle"
            onClick={() => setShowFeedbackHistory(!showFeedbackHistory)}
          >
            Previous Feedback ({feedbackHistory.length}) {showFeedbackHistory ? '▾' : '▸'}
          </button>
          {showFeedbackHistory && (
            <div className="mx-gate-view__feedback-list">
              {feedbackHistory.map((fb, i) => (
                <div key={i} className="mx-gate-view__feedback-entry">
                  <Badge variant="neutral" size="sm">Iteration {fb.iteration}</Badge>
                  <span>{fb.feedback}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="mx-gate-view__stats">
        <div className="mx-gate-view__stat">
          <span className="mx-gate-view__stat-value">
            <Badge variant={VERDICT_VARIANT[verdict ?? ''] ?? 'neutral'}>{verdict ?? '—'}</Badge>
          </span>
          <span className="mx-gate-view__stat-label">Verdict</span>
        </div>
        <div className="mx-gate-view__stat">
          <span className="mx-gate-view__stat-value mx-gate-view__stat-value--disputed">{blockingFindings.length}</span>
          <span className="mx-gate-view__stat-label">Blocking</span>
        </div>
        <div className="mx-gate-view__stat">
          <span className="mx-gate-view__stat-value">{nonBlockingFindings.length}</span>
          <span className="mx-gate-view__stat-label">Non-Blocking</span>
        </div>
        <div className="mx-gate-view__stat">
          <span className="mx-gate-view__stat-value mx-gate-view__stat-value--agreed">{agreed.length}</span>
          <span className="mx-gate-view__stat-label">Agreed</span>
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
            {holisticSummary && (
              <div className="mx-gate-view__section">
                <h4>Holistic Summary</h4>
                <p>{holisticSummary}</p>
              </div>
            )}

            {blockingFindings.length > 0 && (
              <div className="mx-gate-view__section">
                <h4>
                  <Badge variant="error" size="sm">Blocking</Badge>
                  <span>{blockingFindings.length} findings</span>
                </h4>
                {blockingFindings.map((f, i) => (
                  <FindingCard key={i} finding={f as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} />
                ))}
              </div>
            )}

            {nonBlockingFindings.length > 0 && (
              <div className="mx-gate-view__section">
                <h4>
                  <Badge variant="warning" size="sm">Non-Blocking</Badge>
                  <span>{nonBlockingFindings.length} findings</span>
                </h4>
                {nonBlockingFindings.map((f, i) => (
                  <FindingCard key={i} finding={f as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} />
                ))}
              </div>
            )}

            {crossCuttingFindings.length > 0 && (
              <div className="mx-gate-view__section">
                <h4>
                  <Badge variant="info" size="sm">Cross-Cutting</Badge>
                  <span>{crossCuttingFindings.length} findings</span>
                </h4>
                {crossCuttingFindings.map((cc, i) => (
                  <div key={i} className="mx-gate-view__log-entry" style={{ padding: '8px 12px' }}>
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                      <strong>{cc.title}</strong>
                      {cc.origin && <Badge variant="neutral" size="sm">{cc.origin}</Badge>}
                    </div>
                    {cc.domains && cc.domains.length > 0 && (
                      <div style={{ display: 'flex', gap: '4px', marginTop: '4px' }}>
                        {cc.domains.map((d) => <Badge key={d} variant="info" size="sm">{d}</Badge>)}
                      </div>
                    )}
                    {cc.description && <p style={{ margin: '4px 0 0', fontSize: '13px', opacity: 0.85 }}>{cc.description}</p>}
                  </div>
                ))}
              </div>
            )}

            {agreed.length > 0 && (
              <div className="mx-gate-view__section">
                <h4>
                  <Badge variant="success" size="sm">Agreed</Badge>
                  <span>{agreed.length} findings</span>
                </h4>
                {agreed.map((f, i) => {
                  const inner = unwrapFinding(f)
                  return <FindingCard key={i} finding={inner as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} source="BOTH" classification="AGREED" />
                })}
              </div>
            )}

            {aOnly.length > 0 && (
              <div className="mx-gate-view__section">
                <h4>
                  <Badge variant="warning" size="sm">A-Only</Badge>
                  <span>{aOnly.length} findings</span>
                </h4>
                {aOnly.map((f, i) => {
                  const inner = unwrapFinding(f)
                  return <FindingCard key={i} finding={inner as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} source="A" classification="A-ONLY" />
                })}
              </div>
            )}

            {bOnly.length > 0 && (
              <div className="mx-gate-view__section">
                <h4>
                  <Badge variant="warning" size="sm">B-Only</Badge>
                  <span>{bOnly.length} findings</span>
                </h4>
                {bOnly.map((f, i) => {
                  const inner = unwrapFinding(f)
                  return <FindingCard key={i} finding={inner as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} source="B" classification="B-ONLY" />
                })}
              </div>
            )}

            {totalFindings === 0 && !holisticSummary && (
              <p className="mx-gate-view__empty">No synthesis data available yet.</p>
            )}
          </div>
        )}

        {tab === 'comparison' && (
          <ComparisonView reviews={gateReviews} perDomainSynthesis={perDomainSynthesis} />
        )}

        {tab === 'synthesis_log' && (
          <div className="mx-gate-view__synthesis-log">
            {synthesisLog.length === 0 ? (
              <p className="mx-gate-view__empty">No synthesis log entries.</p>
            ) : (
              synthesisLog.map((entry, i) => {
                const findingTitle = typeof entry.finding === 'string'
                  ? entry.finding
                  : (entry.finding as Record<string, unknown>)?.title as string ?? 'Finding'
                const actionLabel = entry.action ?? entry.finding_source ?? entry.type ?? ''
                const actionVariant = actionLabel === 'CONFIRMED' ? 'success'
                  : actionLabel === 'DROPPED' ? 'neutral'
                  : actionLabel === 'PROMOTED' ? 'error'
                  : actionLabel === 'DEMOTED' ? 'info' : 'warning'
                const body = entry.reasoning ?? entry.resolution ?? ''
                return (
                  <div key={i} className="mx-gate-view__log-entry">
                    <div className="mx-gate-view__log-header">
                      {actionLabel && <Badge variant={actionVariant} size="sm">{actionLabel}</Badge>}
                      {entry.agent && <Badge variant="neutral" size="sm">{entry.agent}</Badge>}
                    </div>
                    <div className="mx-gate-view__log-body">
                      <strong>{findingTitle}</strong>
                      {body && <p>{body}</p>}
                      {entry.evidence && <code className="mx-gate-view__log-evidence">{entry.evidence}</code>}
                    </div>
                  </div>
                )
              })
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

        {tab === 'publish' && (
          <PublishPreviewFromGate
            holisticData={holisticData}
            synthData={synthData}
            reviews={gateReviews}
          />
        )}

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
          {!showReviseForm ? (
            <>
              <Button
                variant="primary"
                onClick={handleApprove}
                disabled={submitting || loading}
              >
                {submitting ? <Spinner size="sm" /> : 'Approve & Continue'}
              </Button>
              <Button
                variant="warning"
                onClick={() => setShowReviseForm(true)}
                disabled={submitting || loading}
              >
                Revise
              </Button>
              <button
                className="mx-gate-view__cancel-link"
                onClick={handleCancel}
                disabled={submitting || loading}
              >
                Cancel Workflow
              </button>
            </>
          ) : (
            <div className="mx-gate-view__revise-form">
              <textarea
                className="mx-gate-view__reject-textarea"
                placeholder="Describe what synthesis or holistic analysis should reconsider..."
                value={reviseFeedback}
                onChange={(e) => setReviseFeedback(e.target.value)}
                rows={3}
              />
              <div className="mx-gate-view__reject-btns">
                <Button
                  variant="warning"
                  onClick={handleRevise}
                  disabled={!reviseFeedback.trim() || submitting}
                >
                  {submitting ? <Spinner size="sm" /> : 'Revise & Re-synthesize'}
                </Button>
                <Button variant="ghost" onClick={() => setShowReviseForm(false)}>Back</Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
