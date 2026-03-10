import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import { FindingCard } from './FindingCard'
import { getStepLiveOutput, getAgentDomains, cancelAgentDomain, rerunAgentDomain, parseContent as parseOutputs } from '../../api/workflow-engine'
import type { WorkflowStep, WorkflowArtifact, AgentDomainInfo } from '../../api/workflow-engine'

interface StepContentViewerProps {
  step: WorkflowStep
  artifacts: WorkflowArtifact[]
}

interface ParsedContent {
  [key: string]: unknown
}

interface TokenUsage {
  input_tokens?: number
  output_tokens?: number
  cache_read_input_tokens?: number
  cache_creation_input_tokens?: number
  cost_usd?: number
  duration_ms?: number
  num_turns?: number
}

function formatTokenCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

export { type TokenUsage }

export function TokenUsageBadge({ usage }: { usage: TokenUsage }) {
  const input = usage.input_tokens ?? 0
  const output = usage.output_tokens ?? 0
  if (!input && !output) return null

  const parts: string[] = []
  parts.push(`In: ${formatTokenCount(input)}`)
  parts.push(`Out: ${formatTokenCount(output)}`)
  if (usage.cache_read_input_tokens) {
    parts.push(`Cache read: ${formatTokenCount(usage.cache_read_input_tokens)}`)
  }
  if (usage.num_turns) {
    parts.push(`${usage.num_turns} turns`)
  }
  if (usage.cost_usd != null) {
    parts.push(`$${usage.cost_usd.toFixed(4)}`)
  }

  return (
    <div className="mx-token-usage" title={parts.join(' · ')}>
      <span className="mx-token-usage__icon">T</span>
      <span className="mx-token-usage__summary">
        {formatTokenCount(input + output)} tokens
        {usage.cost_usd != null && <span className="mx-token-usage__cost"> · ${usage.cost_usd.toFixed(4)}</span>}
      </span>
    </div>
  )
}

function parseContent(artifact: WorkflowArtifact): ParsedContent | null {
  const raw = artifact.content_json
  if (!raw) return null
  if (typeof raw === 'string') {
    try { return JSON.parse(raw) } catch { return null }
  }
  return raw as ParsedContent
}

function PRSelectView({ content }: { content: ParsedContent }) {
  const prs = (content.prs ?? content.selected ?? []) as Array<{
    number: number; title?: string; url?: string; author?: string | { login?: string; name?: string }
  }>
  if (!prs.length) return <p className="mx-step-content__empty">No PRs selected.</p>

  return (
    <div className="mx-step-content__pr-list">
      {prs.map((pr) => (
        <div key={pr.number} className="mx-step-content__pr-item">
          <a href={pr.url ?? '#'} target="_blank" rel="noopener noreferrer" className="mx-step-content__pr-link">
            #{pr.number}
          </a>
          <span className="mx-step-content__pr-title">{pr.title ?? ''}</span>
          {pr.author && <span className="mx-step-content__pr-author">@{typeof pr.author === 'object' ? pr.author.login ?? pr.author.name : pr.author}</span>}
        </div>
      ))}
    </div>
  )
}

function PrioritizeView({ content }: { content: ParsedContent }) {
  const prs = (content.prs ?? []) as Array<{
    number?: number; title?: string; priority_score?: number; priority_level?: number; priority_rationale?: string[]
  }>
  const skipped = (content.skipped ?? []) as Array<{ pr_number?: number; reason?: string }>
  const LEVEL_LABELS = ['P0 - Critical', 'P1 - High', 'P2 - Normal', 'P3 - Low']
  const LEVEL_VARIANT: Record<number, 'error' | 'warning' | 'info' | 'neutral'> = { 0: 'error', 1: 'warning', 2: 'info', 3: 'neutral' }

  return (
    <div className="mx-step-content__prioritize">
      {prs.length > 0 && (
        <div className="mx-step-content__pr-list">
          {prs.map((pr) => (
            <div key={pr.number} className="mx-step-content__pr-item">
              <span className="mx-step-content__pr-link">#{pr.number}</span>
              <Badge variant={LEVEL_VARIANT[pr.priority_level ?? 3] ?? 'neutral'} size="sm">
                {LEVEL_LABELS[pr.priority_level ?? 3]}
              </Badge>
              <span className="mx-step-content__pr-title">{pr.title ?? ''}</span>
              <span className="mx-step-content__pr-author">{pr.priority_score?.toFixed(0) ?? '?'} pts</span>
            </div>
          ))}
        </div>
      )}
      {skipped.length > 0 && (
        <div className="mx-step-content__skipped">
          <strong>Skipped ({skipped.length}):</strong>
          {skipped.map((s, i) => (
            <span key={i} className="mx-step-content__skipped-item">
              #{s.pr_number} ({s.reason})
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function PromptView({ content }: { content: ParsedContent }) {
  const prompts = content.prompts as Array<{ pr_number?: number; pr_title?: string; domain?: string; prompt?: string }> | undefined
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})

  if (prompts && prompts.length > 0) {
    return (
      <div className="mx-step-content__prompt-list">
        {prompts.map((p, i) => {
          const isOpen = expanded[i] ?? false
          const sections = parsePromptSections(p.prompt ?? '')
          return (
            <div key={i} className="mx-step-content__prompt-item">
              <div
                className="mx-step-content__prompt-header mx-step-content__prompt-header--clickable"
                onClick={() => setExpanded(prev => ({ ...prev, [i]: !isOpen }))}
              >
                <span className="mx-step-content__prompt-toggle">{isOpen ? '▼' : '▶'}</span>
                {p.pr_number && <strong>#{p.pr_number}</strong>}
                {p.pr_title && <span>{p.pr_title}</span>}
                {p.domain && <Badge variant="info" size="sm">{p.domain}</Badge>}
              </div>
              {isOpen && (
                sections.length > 1 ? (
                  <div className="mx-step-content__prompt-sections">
                    {sections.map((sec, j) => (
                      <PromptSection key={j} title={sec.title} body={sec.body} />
                    ))}
                  </div>
                ) : (
                  <pre className="mx-step-content__prompt">{p.prompt ?? ''}</pre>
                )
              )}
            </div>
          )
        })}
      </div>
    )
  }
  const prompt = (content.prompt ?? content.text ?? JSON.stringify(content, null, 2)) as string
  return <pre className="mx-step-content__prompt">{prompt}</pre>
}

function PromptSection({ title, body }: { title: string; body: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mx-step-content__prompt-section">
      <div
        className="mx-step-content__prompt-section-title"
        onClick={() => setOpen(!open)}
      >
        <span>{open ? '▼' : '▶'}</span> {title}
      </div>
      {open && <pre className="mx-step-content__prompt-section-body">{body}</pre>}
    </div>
  )
}

function parsePromptSections(text: string): Array<{ title: string; body: string }> {
  const lines = text.split('\n')
  const sections: Array<{ title: string; body: string }> = []
  let current: { title: string; lines: string[] } | null = null

  for (const line of lines) {
    if (line.startsWith('## ')) {
      if (current) sections.push({ title: current.title, body: current.lines.join('\n').trim() })
      current = { title: line.slice(3).trim(), lines: [] }
    } else if (current) {
      current.lines.push(line)
    } else {
      if (!sections.length && line.trim()) {
        if (!current) current = { title: 'Header', lines: [] }
        current.lines.push(line)
      }
    }
  }
  if (current) sections.push({ title: current.title, body: current.lines.join('\n').trim() })
  return sections
}

function ReviewView({ content }: { content: ParsedContent }) {
  const reviews = (content.reviews ?? []) as Array<Record<string, unknown>>

  if (reviews.length > 0) {
    return <DomainReviewList reviews={reviews} />
  }

  const md = content.content_md as string | undefined
  if (md) {
    return <SingleReviewMarkdown md={md} content={content} />
  }

  const findings = (content.findings ?? []) as Array<Record<string, unknown>>
  const verdict = content.verdict as string | undefined
  const summary = content.summary as string | undefined

  return (
    <div className="mx-step-content__review">
      {verdict && (
        <div className="mx-step-content__verdict">
          <strong>Verdict:</strong>
          <Badge variant={verdict === 'APPROVE' ? 'success' : verdict === 'REQUEST_CHANGES' ? 'warning' : 'neutral'}>
            {verdict}
          </Badge>
        </div>
      )}
      {summary && <p className="mx-step-content__summary">{summary}</p>}
      {findings.length > 0 && (
        <div className="mx-step-content__findings">
          <h5>Findings ({findings.length})</h5>
          {findings.map((f, i) => (
            <FindingCard key={i} finding={f as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} />
          ))}
        </div>
      )}
    </div>
  )
}

function DomainReviewList({ reviews }: { reviews: Array<Record<string, unknown>> }) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(reviews.length === 1 ? 0 : null)

  const completed = reviews.filter(r => r.status === 'completed')
  const failed = reviews.filter(r => r.status !== 'completed')

  return (
    <div className="mx-step-content__review">
      <div className="mx-step-content__verdict">
        <strong>Agent Reviews:</strong>
        <Badge variant="success" size="sm">{completed.length} completed</Badge>
        {failed.length > 0 && <Badge variant="error" size="sm">{failed.length} failed</Badge>}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
        {reviews.map((r, i) => {
          const domain = (r.domain ?? `PR #${r.pr_number ?? i + 1}`) as string
          const md = r.content_md as string | undefined
          const score = r.score as number | undefined
          const isOpen = expandedIdx === i
          const status = (r.status ?? 'unknown') as string

          return (
            <div key={i} style={{ border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, overflow: 'hidden' }}>
              <div
                onClick={() => setExpandedIdx(isOpen ? null : i)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
                  cursor: 'pointer', background: 'rgba(255,255,255,0.03)',
                }}
              >
                <span>{isOpen ? '\u25BC' : '\u25B6'}</span>
                <Badge variant={status === 'completed' ? 'success' : 'error'} size="sm">{status}</Badge>
                <Badge variant="info" size="sm">{domain}</Badge>
                {score != null && (
                  <Badge variant={score >= 7 ? 'success' : score >= 4 ? 'warning' : 'error'} size="sm">
                    {String(score)}/10
                  </Badge>
                )}
                {r.agent_name ? (
                  <span style={{ fontSize: 12, opacity: 0.5, marginLeft: 'auto' }}>{String(r.agent_name)}</span>
                ) : null}
              </div>
              {isOpen && status === 'completed' && md && (
                <div className="mx-step-content__review-markdown">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
                </div>
              )}
              {isOpen && status !== 'completed' && r.error ? (
                <div className="mx-step-content__error" style={{ margin: '8px 12px', fontSize: 13 }}>{String(r.error)}</div>
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function SingleReviewMarkdown({ md, content }: { md: string; content: ParsedContent }) {
  const domain = content.domain as string | undefined
  const score = content.score as number | undefined

  return (
    <div className="mx-step-content__review">
      {(domain || score != null) && (
        <div className="mx-step-content__verdict">
          {domain && <Badge variant="info" size="sm">{domain}</Badge>}
          {score != null && (
            <Badge variant={score >= 7 ? 'success' : score >= 4 ? 'warning' : 'error'} size="sm">
              Score: {score}/10
            </Badge>
          )}
        </div>
      )}
      <div className="mx-step-content__review-markdown">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
      </div>
    </div>
  )
}

function SynthesisView({ content }: { content: ParsedContent }) {
  const verdict = content.verdict as string | undefined
  const agreed = (content.agreed ?? []) as Array<Record<string, unknown>>
  const aOnly = ((content.a_only ?? content['A-ONLY'] ?? []) as Array<Record<string, unknown>>)
  const bOnly = ((content.b_only ?? content['B-ONLY'] ?? []) as Array<Record<string, unknown>>)
  const summary = content.summary as string | undefined
  const aiVerified = content.ai_verified as boolean | undefined
  const synthFindings = (content.synth_findings ?? []) as Array<Record<string, unknown>>
  const crossCuttingFlags = (content.cross_cutting_flags ?? []) as string[]
  const falsePositivesDropped = (content.false_positives_dropped ?? []) as Array<{ title?: string; reason?: string }>
  const synthesisLog = (content.synthesis_log ?? []) as Array<{ finding?: string; action?: string; reasoning?: string }>
  const rawPerDomain = content.per_domain_synthesis
  const perDomainList: Array<Record<string, unknown>> = Array.isArray(rawPerDomain)
    ? rawPerDomain as Array<Record<string, unknown>>
    : rawPerDomain && typeof rawPerDomain === 'object'
      ? Object.values(rawPerDomain as Record<string, Record<string, unknown>>)
      : []
  const questions = (content.questions ?? []) as string[]
  const [showLog, setShowLog] = useState(false)

  return (
    <div className="mx-step-content__synthesis">
      {verdict && (
        <div className="mx-step-content__verdict">
          <strong>Final Verdict:</strong>
          <Badge variant={verdict === 'APPROVE' ? 'success' : 'warning'}>{verdict}</Badge>
          {aiVerified && <Badge variant="info" size="sm">AI Verified</Badge>}
        </div>
      )}
      {summary && <p className="mx-step-content__summary">{summary}</p>}

      <div className="mx-step-content__classification-grid">
        <Section label="Agreed" variant="success" items={agreed} classification="AGREED" />
        <Section label="Agent A Only" variant="warning" items={aOnly} classification="A-ONLY" />
        <Section label="Agent B Only" variant="warning" items={bOnly} classification="B-ONLY" />
        {synthFindings.length > 0 && (
          <SynthSection items={synthFindings} />
        )}
      </div>

      {crossCuttingFlags.length > 0 && (
        <div className="mx-step-content__class-section">
          <h5><Badge variant="info" size="sm">Cross-Cutting Flags</Badge> {crossCuttingFlags.length}</h5>
          <ul className="mx-step-content__flag-list">
            {crossCuttingFlags.map((flag, i) => <li key={i}>{flag}</li>)}
          </ul>
        </div>
      )}

      {falsePositivesDropped.length > 0 && (
        <div className="mx-step-content__class-section">
          <h5><Badge variant="neutral" size="sm">False Positives Dropped</Badge> {falsePositivesDropped.length}</h5>
          {falsePositivesDropped.map((fp, i) => (
            <div key={i} className="mx-step-content__pr-item">
              <strong>{fp.title}</strong>
              <span className="mx-step-content__pr-title">{fp.reason}</span>
            </div>
          ))}
        </div>
      )}

      {questions.length > 0 && (
        <div className="mx-step-content__class-section">
          <h5>Questions ({questions.length})</h5>
          <ol>{questions.map((q, i) => <li key={i}>{q}</li>)}</ol>
        </div>
      )}

      {perDomainList.length > 0 && (
        <div className="mx-step-content__class-section">
          <h5>Per-Domain Synthesis ({perDomainList.length} domains)</h5>
          {perDomainList.map((ds, i) => {
            const domain = String(ds.domain ?? `Domain ${i + 1}`)
            const domainVerdict = String(ds.verdict ?? 'COMMENT')
            const totalFindings = Number(ds.total_findings ?? 0)
            const agreedCount = Array.isArray(ds.agreed) ? (ds.agreed as unknown[]).length : 0
            const aOnlyCount = Array.isArray(ds.a_only) ? (ds.a_only as unknown[]).length : 0
            const bOnlyCount = Array.isArray(ds.b_only) ? (ds.b_only as unknown[]).length : 0
            return (
              <div key={i} className="mx-step-content__pr-item" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '4px' }}>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                  <Badge variant="info" size="sm">{domain}</Badge>
                  <Badge variant={domainVerdict === 'APPROVE' ? 'success' : domainVerdict === 'CHANGES_REQUESTED' ? 'error' : 'warning'} size="sm">
                    {domainVerdict}
                  </Badge>
                  <span style={{ fontSize: '12px', opacity: 0.7 }}>
                    {totalFindings} findings ({agreedCount} agreed, {aOnlyCount} A-only, {bOnlyCount} B-only)
                  </span>
                </div>
                {ds.agent_a ? (
                  <span style={{ fontSize: '11px', opacity: 0.5 }}>A: {String(ds.agent_a)} / B: {String(ds.agent_b ?? '?')}</span>
                ) : null}
              </div>
            )
          })}
        </div>
      )}

      {synthesisLog.length > 0 && (
        <div className="mx-step-content__class-section">
          <h5
            style={{ cursor: 'pointer' }}
            onClick={() => setShowLog(!showLog)}
          >
            {showLog ? '▼' : '▶'} Classification Reasoning ({synthesisLog.length})
          </h5>
          {showLog && synthesisLog.map((entry, i) => (
            <div key={i} className="mx-step-content__pr-item" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
              <div style={{ display: 'flex', gap: '8px' }}>
                <Badge variant={entry.action === 'CONFIRMED' ? 'success' : entry.action === 'DROPPED' ? 'neutral' : 'warning'} size="sm">
                  {entry.action}
                </Badge>
                <strong>{entry.finding}</strong>
              </div>
              {entry.reasoning && <p style={{ margin: '4px 0 0', fontSize: '13px', opacity: 0.85 }}>{entry.reasoning}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function SynthSection({ items }: { items: Array<Record<string, unknown>> }) {
  if (!items.length) return null
  return (
    <div className="mx-step-content__class-section">
      <h5>
        <Badge variant="info" size="sm">SYNTH</Badge>
        <span className="mx-step-content__class-count">{items.length}</span>
      </h5>
      {items.map((f, i) => (
        <FindingCard
          key={i}
          finding={f as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }}
          classification="SYNTH"
        />
      ))}
    </div>
  )
}

function Section({ label, variant, items, classification }: {
  label: string; variant: 'success' | 'warning'; items: Array<Record<string, unknown>>; classification: string
}) {
  if (!items.length) return null
  return (
    <div className="mx-step-content__class-section">
      <h5>
        <Badge variant={variant} size="sm">{label}</Badge>
        <span className="mx-step-content__class-count">{items.length}</span>
      </h5>
      {items.map((f, i) => (
        <FindingCard
          key={i}
          finding={f as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }}
          classification={classification}
        />
      ))}
    </div>
  )
}

function FreshnessView({ content }: { content: ParsedContent }) {
  const checks = (content.checks ?? content.results ?? []) as Array<{
    pr_number?: number; status?: string; classification?: string; head_sha?: string; reviewed_sha?: string
    recommendation?: string; affected_findings?: string[]; unaffected_findings?: string[]
    changed_files?: string[]; current_sha?: string
  }>
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)
  if (!checks.length) return <p className="mx-step-content__empty">No freshness data.</p>

  return (
    <div className="mx-step-content__freshness">
      {checks.map((c, i) => {
        const cls = c.status ?? c.classification ?? 'UNKNOWN'
        const isOpen = expandedIdx === i
        return (
          <div key={i} className="mx-step-content__freshness-item" style={{ flexDirection: 'column', cursor: 'pointer' }} onClick={() => setExpandedIdx(isOpen ? null : i)}>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', width: '100%' }}>
              <span className="mx-step-content__freshness-pr">#{c.pr_number}</span>
              <Badge
                variant={cls === 'CURRENT' ? 'success' : cls === 'STALE-MINOR' ? 'warning' : 'error'}
                size="sm"
              >
                {cls}
              </Badge>
              {c.head_sha && <code className="mx-step-content__sha">{(c.head_sha ?? c.current_sha ?? '').slice(0, 8)}</code>}
              <span style={{ marginLeft: 'auto', fontSize: '12px', opacity: 0.6 }}>{isOpen ? '▼' : '▶'}</span>
            </div>
            {c.recommendation && (
              <p style={{ margin: '6px 0 0', fontWeight: 500, fontSize: '13px' }}>{c.recommendation}</p>
            )}
            {isOpen && (
              <div style={{ marginTop: '8px', width: '100%' }}>
                {c.affected_findings && c.affected_findings.length > 0 && (
                  <div style={{ marginBottom: '6px' }}>
                    <strong style={{ fontSize: '12px' }}>Potentially Affected:</strong>
                    <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '2px' }}>
                      {c.affected_findings.map((f, j) => <Badge key={j} variant="warning" size="sm">{f}</Badge>)}
                    </div>
                  </div>
                )}
                {c.unaffected_findings && c.unaffected_findings.length > 0 && (
                  <div style={{ marginBottom: '6px' }}>
                    <strong style={{ fontSize: '12px' }}>Unaffected:</strong>
                    <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '2px' }}>
                      {c.unaffected_findings.map((f, j) => <Badge key={j} variant="success" size="sm">{f}</Badge>)}
                    </div>
                  </div>
                )}
                {c.changed_files && c.changed_files.length > 0 && (
                  <div>
                    <strong style={{ fontSize: '12px' }}>Changed files since review:</strong>
                    <ul style={{ margin: '2px 0 0', paddingLeft: '16px', fontSize: '12px' }}>
                      {c.changed_files.slice(0, 20).map((f, j) => <li key={j}><code>{f}</code></li>)}
                      {c.changed_files.length > 20 && <li>...and {c.changed_files.length - 20} more</li>}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function HumanGateView({ step, instanceId }: { step: WorkflowStep; instanceId?: number }) {
  const statusLabel = step.status === 'awaiting_gate' ? 'Awaiting human decision' : step.status
  const gateOutputs = parseOutputs(step.outputs_json) as Record<string, unknown> | null
  const gatePayload = (gateOutputs?.gate_payload ?? gateOutputs) as Record<string, unknown> | null
  const gateType = (gatePayload?.type ?? 'unknown') as string
  const payload = gatePayload ?? {} as Record<string, unknown>

  const typeLabel = gateType === 'prompt_review' ? 'Prompt Review Gate'
    : gateType === 'review_gate' ? 'Final Review Gate'
    : 'Human Gate'

  let contextLine = ''
  if (gateType === 'prompt_review') {
    const promptCount = (payload.prompts as unknown[] ?? []).length
    const expertCount = (payload.experts as unknown[] ?? []).length
    contextLine = `${promptCount} prompts from ${expertCount} expert domains ready for review`
  } else if (gateType === 'review_gate') {
    const synth = (payload.synthesis ?? {}) as Record<string, unknown>
    const holistic = (payload.holistic ?? {}) as Record<string, unknown>
    const total = (synth.total_findings ?? 0) as number
    const blocking = (holistic.blocking_findings as unknown[] ?? []).length
    const verdict = ((holistic.verdict ?? synth.verdict ?? '') as string)
    contextLine = `${verdict ? verdict + ' — ' : ''}${total} findings, ${blocking} blocking`
  }

  if (step.status === 'completed' && gateType === 'review_gate') {
    return <CompletedReviewGateView payload={payload} instanceId={instanceId} />
  }

  return (
    <div className="mx-step-content__gate">
      <Badge variant={step.status === 'awaiting_gate' ? 'warning' : step.status === 'completed' ? 'success' : 'neutral'}>
        {statusLabel}
      </Badge>
      <div style={{ marginTop: '6px' }}>
        <strong>{typeLabel}</strong>
        {contextLine && <p style={{ margin: '4px 0 0', fontSize: '13px', opacity: 0.85 }}>{contextLine}</p>}
      </div>
      {step.status === 'completed' && <p>Gate has been resolved.</p>}
    </div>
  )
}

function CompletedReviewGateView({ payload, instanceId }: { payload: Record<string, unknown>; instanceId?: number }) {
  const synth = (payload.synthesis ?? {}) as Record<string, unknown>
  const holistic = (payload.holistic ?? {}) as Record<string, unknown>
  const verdict = (holistic.verdict ?? synth.verdict ?? 'COMMENT') as string
  const summary = (holistic.summary ?? '') as string
  const blocking = (holistic.blocking_findings ?? []) as Array<Record<string, unknown>>
  const nonBlocking = (holistic.non_blocking_findings ?? []) as Array<Record<string, unknown>>
  const crossCutting = (holistic.cross_cutting_findings ?? []) as Array<{ title?: string; domains?: string[]; description?: string; origin?: string }>
  const agreed = (synth.agreed ?? []) as Array<Record<string, unknown>>
  const aOnly = ((synth.a_only ?? synth['A-ONLY'] ?? []) as Array<Record<string, unknown>>)
  const bOnly = ((synth.b_only ?? synth['B-ONLY'] ?? []) as Array<Record<string, unknown>>)
  const domains = (holistic.domain_coverage ?? []) as string[]
  const totalFindings = agreed.length + aOnly.length + bOnly.length
  const reviews = (payload.reviews ?? []) as Array<Record<string, unknown>>
  const confidence = holistic.confidence as string | undefined

  const markdown = buildFinalReviewMarkdown({
    verdict, summary, blocking, nonBlocking, crossCutting,
    agreed, aOnly, bOnly, domains, totalFindings, reviews, confidence,
  })

  const handleDownload = (format: 'md' | 'json') => {
    const blob = format === 'md'
      ? new Blob([markdown], { type: 'text/markdown' })
      : new Blob([JSON.stringify({ holistic, synthesis: synth }, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `review${instanceId ? `-run-${instanceId}` : ''}.${format}`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="mx-step-content__gate">
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
        <Badge variant="success">Approved</Badge>
        <Badge variant={verdict === 'APPROVE' ? 'success' : verdict === 'REQUEST_CHANGES' ? 'error' : 'warning'}>
          {verdict}
        </Badge>
        {confidence && <Badge variant="neutral" size="sm">{confidence} confidence</Badge>}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <Button variant="primary" size="sm" onClick={() => handleDownload('md')}>
            Download .md
          </Button>
          <Button variant="ghost" size="sm" onClick={() => handleDownload('json')}>
            Download .json
          </Button>
        </div>
      </div>
      <div className="mx-step-content__review-markdown">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
      </div>
    </div>
  )
}

function buildFinalReviewMarkdown(data: {
  verdict: string; summary: string
  blocking: Array<Record<string, unknown>>; nonBlocking: Array<Record<string, unknown>>
  crossCutting: Array<{ title?: string; domains?: string[]; description?: string; origin?: string }>
  agreed: Array<Record<string, unknown>>; aOnly: Array<Record<string, unknown>>; bOnly: Array<Record<string, unknown>>
  domains: string[]; totalFindings: number
  reviews: Array<Record<string, unknown>>; confidence?: string
}): string {
  const { verdict, summary, blocking, nonBlocking, crossCutting, agreed, aOnly, bOnly, domains, totalFindings, reviews, confidence } = data
  const lines: string[] = []
  lines.push(`# Adversarial Code Review — ${verdict}\n`)
  if (confidence) lines.push(`**Confidence:** ${confidence}\n`)
  if (summary) lines.push(`${summary}\n`)
  lines.push(`**${totalFindings}** findings across **${domains.length}** domains | **${blocking.length}** blocking | **${agreed.length}** agreed by both agents\n`)
  lines.push(`---\n`)

  if (blocking.length > 0) {
    lines.push(`## Blocking Findings (${blocking.length})\n`)
    blocking.forEach((f, i) => {
      const title = (f.title ?? 'Untitled') as string
      const severity = (f.severity ?? '') as string
      const domain = (f.domain ?? '') as string
      const desc = (f.description ?? f.problem ?? '') as string
      lines.push(`### ${i + 1}. [${severity}] ${title}${domain ? ` _(${domain})_` : ''}\n`)
      if (desc) lines.push(`${desc}\n`)
      const loc = f.location as Record<string, unknown> | undefined
      if (loc?.file) lines.push(`**File:** \`${loc.file}\`${loc.start_line ? `:${loc.start_line}` : ''}\n`)
      const fix = (f.fix ?? f.suggestion ?? '') as string
      if (fix) lines.push(`**Fix:** ${fix}\n`)
    })
  }

  if (nonBlocking.length > 0) {
    lines.push(`## Non-Blocking Findings (${nonBlocking.length})\n`)
    nonBlocking.forEach((f, i) => {
      const title = (f.title ?? 'Untitled') as string
      const severity = (f.severity ?? '') as string
      const desc = (f.description ?? f.problem ?? '') as string
      lines.push(`### ${i + 1}. [${severity}] ${title}\n`)
      if (desc) lines.push(`${desc}\n`)
    })
  }

  if (crossCutting.length > 0) {
    lines.push(`## Cross-Cutting Concerns (${crossCutting.length})\n`)
    crossCutting.forEach((cc, i) => {
      lines.push(`${i + 1}. **${cc.title}**${cc.domains?.length ? ` _(${cc.domains.join(', ')})_` : ''}`)
      if (cc.description) lines.push(`   ${cc.description}\n`)
    })
  }

  if (agreed.length > 0) {
    lines.push(`## Agreed Findings (${agreed.length})\n`)
    agreed.forEach((f, i) => {
      const inner = (f.finding_a ?? f.finding ?? f) as Record<string, unknown>
      const title = (inner.title ?? 'Untitled') as string
      const severity = (inner.severity ?? '') as string
      lines.push(`${i + 1}. **[${severity}]** ${title}`)
    })
    lines.push('')
  }

  if (aOnly.length > 0) {
    lines.push(`## Agent A Only (${aOnly.length})\n`)
    aOnly.forEach((f, i) => {
      const inner = (f.finding_a ?? f.finding ?? f) as Record<string, unknown>
      const title = (inner.title ?? 'Untitled') as string
      const severity = (inner.severity ?? '') as string
      lines.push(`${i + 1}. **[${severity}]** ${title}`)
    })
    lines.push('')
  }

  if (bOnly.length > 0) {
    lines.push(`## Agent B Only (${bOnly.length})\n`)
    bOnly.forEach((f, i) => {
      const inner = (f.finding_b ?? f.finding ?? f) as Record<string, unknown>
      const title = (inner.title ?? 'Untitled') as string
      const severity = (inner.severity ?? '') as string
      lines.push(`${i + 1}. **[${severity}]** ${title}`)
    })
    lines.push('')
  }

  lines.push(`---\n_Generated by adversarial review (${reviews.length} expert reviews across ${domains.length} domains)_`)
  return lines.join('\n')
}

function PublishView({ content }: { content: ParsedContent }) {
  const published = content.published
  const allPublished = content.all_published as boolean | undefined
  const reason = content.reason as string | undefined
  const prNumber = content.pr_number as number | undefined
  const verdict = content.verdict as string | undefined
  const commentUrl = content.comment_url as string | undefined
  const commentBody = content.comment_body as string | undefined
  const eventType = content.event_type as string | undefined

  if (reason) {
    return (
      <div className="mx-step-content__gate">
        <Badge variant="neutral">Not Published</Badge>
        <p>{reason}</p>
      </div>
    )
  }

  if (Array.isArray(published)) {
    return (
      <div className="mx-step-content__publish">
        <div className="mx-step-content__verdict">
          <strong>Multi-PR Publication:</strong>
          <Badge variant={allPublished ? 'success' : 'warning'}>
            {allPublished ? 'All Published' : 'Partially Published'}
          </Badge>
        </div>
        {published.map((r: Record<string, unknown>, i: number) => (
          <div key={i} className="mx-step-content__pr-item" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <strong>PR #{String(r.pr_number)}</strong>
              <Badge variant={r.published ? 'success' : 'error'} size="sm">
                {r.published ? 'Published' : 'Failed'}
              </Badge>
              {r.event_type ? <Badge variant="neutral" size="sm">{String(r.event_type)}</Badge> : null}
            </div>
            {r.comment_url ? (
              <a href={String(r.comment_url)} target="_blank" rel="noopener noreferrer" style={{ fontSize: '13px' }}>
                View on GitHub
              </a>
            ) : null}
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="mx-step-content__publish">
      <div className="mx-step-content__verdict">
        <Badge variant={content.published ? 'success' : 'error'}>
          {content.published ? 'Published' : 'Not Published'}
        </Badge>
        {prNumber && <strong>PR #{prNumber}</strong>}
        {verdict && <Badge variant={verdict === 'APPROVE' ? 'success' : 'warning'} size="sm">{verdict}</Badge>}
        {eventType && <Badge variant="neutral" size="sm">{eventType}</Badge>}
      </div>
      {commentUrl && (
        <a href={commentUrl} target="_blank" rel="noopener noreferrer" className="mx-step-content__pr-link">
          View on GitHub
        </a>
      )}
      {commentBody && (
        <details style={{ marginTop: '8px' }}>
          <summary style={{ cursor: 'pointer', fontSize: '13px' }}>Comment Preview</summary>
          <pre className="mx-step-content__prompt" style={{ maxHeight: '400px', overflow: 'auto' }}>{commentBody}</pre>
        </details>
      )}
    </div>
  )
}

function DefaultView({ content }: { content: ParsedContent }) {
  return <pre className="mx-step-content__raw">{JSON.stringify(content, null, 2)}</pre>
}

function ExpertSelectView({ content }: { content: ParsedContent }) {
  const experts = (content.experts ?? []) as Array<{
    domain_id?: string; domain?: string; display_name?: string; persona?: string
    scope?: string; checklist?: string[]; anti_patterns?: string[]
    matched_files?: string[]; relevance_pct?: number; perspective?: string
  }>
  const prDomains = (content.pr_domains ?? []) as Array<{ pr_number?: number; domains?: string[]; file_count?: number }>
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  return (
    <div className="mx-step-content__expert-select">
      {experts.length > 0 && (
        <>
          <h5>Expert Domains ({experts.length})</h5>
          <div className="mx-step-content__expert-list">
            {experts.map((e, i) => {
              const isOpen = expandedIdx === i
              return (
                <div key={i} className="mx-step-content__expert-card">
                  <div
                    className="mx-step-content__expert-header"
                    onClick={() => setExpandedIdx(isOpen ? null : i)}
                  >
                    <Badge variant="info" size="sm">{e.display_name ?? e.domain_id ?? e.domain}</Badge>
                    {e.relevance_pct != null && (
                      <Badge variant="neutral" size="sm">{e.relevance_pct.toFixed(0)}% relevance</Badge>
                    )}
                    {e.checklist && <span className="mx-step-content__expert-meta">{e.checklist.length} checks</span>}
                    {e.anti_patterns && e.anti_patterns.length > 0 && (
                      <span className="mx-step-content__expert-meta">{e.anti_patterns.length} anti-patterns</span>
                    )}
                    <span className="mx-step-content__prompt-toggle">{isOpen ? '▼' : '▶'}</span>
                  </div>
                  {isOpen && (
                    <div className="mx-step-content__expert-detail">
                      {e.persona && <p className="mx-step-content__expert-persona">{e.persona}</p>}
                      {e.scope && <p><strong>Scope:</strong> {e.scope}</p>}
                      {e.matched_files && e.matched_files.length > 0 && (
                        <div>
                          <strong>Matched files:</strong>
                          <ul>{e.matched_files.slice(0, 10).map((f, j) => <li key={j}><code>{f}</code></li>)}</ul>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </>
      )}
      {prDomains.length > 0 && (
        <>
          <h5>PR Domains</h5>
          <div className="mx-step-content__pr-list">
            {prDomains.map((pd, i) => (
              <div key={i} className="mx-step-content__pr-item">
                <span className="mx-step-content__pr-link">#{pd.pr_number}</span>
                {(pd.domains ?? []).map((d) => (
                  <Badge key={d} variant="neutral" size="sm">{d}</Badge>
                ))}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function HolisticView({ content }: { content: ParsedContent }) {
  const verdict = content.verdict as string | undefined
  const confidence = content.confidence as string | undefined
  const summary = content.summary as string | undefined
  const aiPowered = content.ai_powered as boolean | undefined
  const blocking = (content.blocking_findings ?? content.blocking ?? []) as Array<Record<string, unknown>>
  const nonBlocking = (content.non_blocking_findings ?? content.non_blocking ?? []) as Array<Record<string, unknown>>
  const crossCutting = (content.cross_cutting_findings ?? []) as Array<{ title?: string; domains?: string[]; description?: string; origin?: string }>
  const domainVerdicts = (content.domain_verdicts ?? []) as Array<{ domain?: string; verdict?: string; finding_count?: number }>
  const domainCoverage = (content.domain_coverage ?? []) as string[]
  const crossDomainInteractions = (content.cross_domain_interactions ?? []) as Array<{ files?: string[]; domains?: string[]; description?: string }>
  const analysisLog = (content.holistic_analysis_log ?? []) as Array<{ action?: string; finding?: string; reasoning?: string }>
  const recs = (content.recommendations ?? []) as Array<{ priority?: string; text?: string }>
  const [showLog, setShowLog] = useState(false)

  return (
    <div className="mx-step-content__holistic">
      {verdict && (
        <div className="mx-step-content__verdict">
          <strong>Verdict:</strong>
          <Badge variant={verdict === 'APPROVE' ? 'success' : verdict === 'REQUEST_CHANGES' ? 'error' : 'warning'}>
            {verdict}
          </Badge>
          {confidence && <Badge variant="neutral" size="sm">{confidence} confidence</Badge>}
          {aiPowered && <Badge variant="info" size="sm">AI-Powered</Badge>}
        </div>
      )}
      {summary && <p className="mx-step-content__summary">{summary}</p>}

      {domainCoverage.length > 0 && (
        <div className="mx-step-content__verdict" style={{ marginTop: '8px' }}>
          <strong>Domains:</strong>
          {domainCoverage.map((d) => <Badge key={d} variant="info" size="sm">{d}</Badge>)}
        </div>
      )}

      {domainVerdicts.length > 0 && (
        <div className="mx-step-content__class-section">
          <h5>Per-Domain Verdicts</h5>
          {domainVerdicts.map((dv, i) => (
            <div key={i} className="mx-step-content__pr-item">
              <Badge variant="info" size="sm">{dv.domain}</Badge>
              <Badge variant={dv.verdict === 'APPROVE' ? 'success' : dv.verdict === 'REQUEST_CHANGES' ? 'error' : 'warning'} size="sm">
                {dv.verdict}
              </Badge>
              <span>{dv.finding_count ?? 0} findings</span>
            </div>
          ))}
        </div>
      )}

      {blocking.length > 0 && (
        <div className="mx-step-content__class-section">
          <h5><Badge variant="error" size="sm">Blocking</Badge> {blocking.length}</h5>
          {blocking.map((f, i) => {
            const inner = (f.finding_a ?? f.finding ?? f) as Record<string, unknown>
            return <FindingCard key={i} finding={inner as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} />
          })}
        </div>
      )}
      {nonBlocking.length > 0 && (
        <div className="mx-step-content__class-section">
          <h5><Badge variant="warning" size="sm">Non-Blocking</Badge> {nonBlocking.length}</h5>
          {nonBlocking.map((f, i) => {
            const inner = (f.finding_a ?? f.finding ?? f) as Record<string, unknown>
            return <FindingCard key={i} finding={inner as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} />
          })}
        </div>
      )}

      {crossCutting.length > 0 && (
        <div className="mx-step-content__class-section">
          <h5><Badge variant="info" size="sm">Cross-Cutting</Badge> {crossCutting.length}</h5>
          {crossCutting.map((cc, i) => (
            <div key={i} className="mx-step-content__pr-item" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
              <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                <strong>{cc.title}</strong>
                {cc.origin && <Badge variant="neutral" size="sm">{cc.origin}</Badge>}
              </div>
              {cc.domains && cc.domains.length > 0 && (
                <div style={{ display: 'flex', gap: '4px', marginTop: '4px' }}>
                  {cc.domains.map((d) => <Badge key={d} variant="info" size="sm">{d}</Badge>)}
                </div>
              )}
              {cc.description && <p style={{ margin: '4px 0 0', fontSize: '13px' }}>{cc.description}</p>}
            </div>
          ))}
        </div>
      )}

      {crossDomainInteractions.length > 0 && (
        <div className="mx-step-content__class-section">
          <h5>Cross-Domain Interactions</h5>
          {crossDomainInteractions.map((cdi, i) => (
            <div key={i} className="mx-step-content__pr-item" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
              {cdi.domains && <div>{cdi.domains.map((d) => <Badge key={d} variant="neutral" size="sm">{d}</Badge>)}</div>}
              {cdi.description && <p style={{ margin: '2px 0 0', fontSize: '13px' }}>{cdi.description}</p>}
              {cdi.files && cdi.files.length > 0 && (
                <div style={{ fontSize: '12px', opacity: 0.7 }}>{cdi.files.join(', ')}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {recs.length > 0 && (
        <div className="mx-step-content__class-section">
          <h5>Recommendations</h5>
          {recs.map((r, i) => (
            <div key={i} className="mx-step-content__pr-item">
              <Badge variant={r.priority === 'must_fix' ? 'error' : 'warning'} size="sm">{r.priority}</Badge>
              <span className="mx-step-content__pr-title">{r.text}</span>
            </div>
          ))}
        </div>
      )}

      {analysisLog.length > 0 && (
        <div className="mx-step-content__class-section">
          <h5 style={{ cursor: 'pointer' }} onClick={() => setShowLog(!showLog)}>
            {showLog ? '▼' : '▶'} Analysis Log ({analysisLog.length})
          </h5>
          {showLog && analysisLog.map((entry, i) => (
            <div key={i} className="mx-step-content__pr-item" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
              <div style={{ display: 'flex', gap: '6px' }}>
                <Badge variant={entry.action === 'PROMOTED' ? 'error' : entry.action === 'DEMOTED' ? 'success' : 'info'} size="sm">{entry.action}</Badge>
                <strong>{entry.finding}</strong>
              </div>
              {entry.reasoning && <p style={{ margin: '4px 0 0', fontSize: '13px', opacity: 0.85 }}>{entry.reasoning}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function FollowupCheckView({ content }: { content: ParsedContent }) {
  const results = (content.results ?? content.followup_results ?? []) as Array<{
    followup_id?: number; pr_number?: number; classification?: string
    has_new_commits?: boolean; new_comment_count?: number
  }>
  if (!results.length) return <p className="mx-step-content__empty">No follow-up results.</p>

  const CLS_VARIANT: Record<string, 'success' | 'warning' | 'error' | 'info' | 'neutral'> = {
    RESOLVED: 'success', PARTIALLY_RESOLVED: 'warning', AUTHOR_DISAGREES: 'error',
    NO_RESPONSE: 'neutral', DISCUSSING: 'info', MERGED: 'success', CLOSED: 'neutral',
  }

  return (
    <div className="mx-step-content__followup-check">
      {results.map((r, i) => (
        <div key={i} className="mx-step-content__pr-item">
          <span className="mx-step-content__pr-link">#{r.pr_number}</span>
          <Badge variant={CLS_VARIANT[r.classification ?? ''] ?? 'neutral'} size="sm">
            {r.classification ?? 'UNKNOWN'}
          </Badge>
          {r.has_new_commits && <Badge variant="info" size="sm">New commits</Badge>}
          {(r.new_comment_count ?? 0) > 0 && <span>{r.new_comment_count} new comments</span>}
        </div>
      ))}
    </div>
  )
}

function FollowupActionView({ content }: { content: ParsedContent }) {
  const actions = (content.actions ?? content.actions_taken ?? []) as Array<{
    pr_number?: number; action?: string; classification?: string; reason?: string
  }>
  if (!actions.length) return <p className="mx-step-content__empty">No actions taken.</p>

  return (
    <div className="mx-step-content__followup-action">
      {actions.map((a, i) => (
        <div key={i} className="mx-step-content__pr-item">
          <span className="mx-step-content__pr-link">#{a.pr_number}</span>
          <Badge variant={a.action === 'comment_posted' ? 'success' : a.action === 'skip' ? 'neutral' : 'error'} size="sm">
            {a.action}
          </Badge>
          {a.reason && <span className="mx-step-content__pr-title">{a.reason}</span>}
        </div>
      ))}
    </div>
  )
}

const VIEWERS: Record<string, React.FC<{ content: ParsedContent; step: WorkflowStep; instanceId?: number }>> = {
  pr_select: ({ content }) => <PRSelectView content={content} />,
  prioritize: ({ content }) => <PrioritizeView content={content} />,
  prompt_generate: ({ content }) => <PromptView content={content} />,
  agent_review: ({ content }) => <ReviewView content={content} />,
  synthesis: ({ content }) => <SynthesisView content={content} />,
  freshness_check: ({ content }) => <FreshnessView content={content} />,
  human_gate: ({ step, instanceId }) => <HumanGateView step={step} instanceId={instanceId} />,
  publish: ({ content }) => <PublishView content={content} />,
  expert_select: ({ content }) => <ExpertSelectView content={content} />,
  holistic_review: ({ content }) => <HolisticView content={content} />,
  followup_check: ({ content }) => <FollowupCheckView content={content} />,
  followup_action: ({ content }) => <FollowupActionView content={content} />,
}

function AgentDomainTracker({ instanceId, stepId }: { instanceId: number; stepId: string }) {
  const [domains, setDomains] = useState<Record<string, AgentDomainInfo>>({})
  const [output, setOutput] = useState('')

  useEffect(() => {
    let active = true
    const poll = async () => {
      try {
        const [d, o] = await Promise.all([
          getAgentDomains(instanceId, stepId),
          getStepLiveOutput(instanceId, stepId),
        ])
        if (active) { setDomains(d); setOutput(o) }
      } catch { /* ignore */ }
    }
    poll()
    const iv = setInterval(poll, 3000)
    return () => { active = false; clearInterval(iv) }
  }, [instanceId, stepId])

  const entries = Object.entries(domains)
  const runningCount = entries.filter(([, d]) => d.status === 'running').length
  const completedCount = entries.filter(([, d]) => d.status === 'completed').length
  const failedCount = entries.filter(([, d]) => d.status === 'failed' || d.status === 'cancelled').length
  const totalCount = entries.length

  const domainSections = parseDomainSections(output)
  const sectionMap = new Map(domainSections.map(s => [s.domain, s.content]))

  if (!entries.length && !output) {
    return (
      <div className="mx-step-content__running">
        <Spinner size="sm" />
        <span>Starting agents...</span>
      </div>
    )
  }

  if (entries.length > 0) {
    return (
      <div className="mx-step-content__live">
        <div className="mx-step-content__live-header">
          {runningCount > 0 && <Spinner size="sm" />}
          <span>
            Agents: {completedCount}/{totalCount} complete
            {failedCount > 0 && ` (${failedCount} failed)`}
            {runningCount > 0 && ` \u2014 ${runningCount} running`}
          </span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
          {entries.map(([domain, info]) => (
            <AgentDomainCard
              key={domain}
              domain={domain}
              info={info}
              liveContent={sectionMap.get(domain)}
              instanceId={instanceId}
              stepId={stepId}
            />
          ))}
        </div>
      </div>
    )
  }

  if (domainSections.length > 1) {
    return (
      <div className="mx-step-content__live">
        <div className="mx-step-content__live-header">
          <Spinner size="sm" />
          <span>Agents working ({domainSections.length} domains)</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
          {domainSections.map((sec) => (
            <DomainLiveFallbackCard key={sec.domain} domain={sec.domain} content={sec.content} />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="mx-step-content__live">
      <div className="mx-step-content__live-header">
        <Spinner size="sm" />
        <span>Agent output (live)</span>
      </div>
      <pre className="mx-step-content__live-terminal">{output}</pre>
    </div>
  )
}

function extractLatestThought(text: string): string {
  if (!text) return 'Thinking...'
  const cleaned = text
    .replace(/\[Using tool: [^\]]*\]/g, '')
    .replace(/\n{2,}/g, '\n')
  const sentences = cleaned.split(/(?<=\.)\s+|\n/).filter((s) => {
    const t = s.trim()
    return t.length > 10 && /[a-zA-Z]/.test(t)
  })
  if (!sentences.length) return 'Thinking...'
  let thought = sentences[sentences.length - 1].trim()
  if (thought.length > 150) thought = thought.slice(0, 147) + '...'
  return thought
}


function AgentDomainCard({ domain, info, liveContent, instanceId, stepId }: {
  domain: string; info: AgentDomainInfo; liveContent?: string
  instanceId: number; stepId: string
}) {
  const isCompleted = info.status === 'completed'
  const isRunning = info.status === 'running'
  const [open, setOpen] = useState(isCompleted)
  const [showTerminal, setShowTerminal] = useState(false)
  const [acting, setActing] = useState(false)
  const ref = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (ref.current && showTerminal) ref.current.scrollTop = ref.current.scrollHeight
  }, [liveContent, showTerminal])

  const now = Date.now() / 1000
  const elapsed = info.started_at
    ? Math.round((info.completed_at || now) - info.started_at)
    : 0
  const elapsedStr = elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`

  const statusVariant: Record<string, 'success' | 'warning' | 'error' | 'info' | 'neutral'> = {
    running: 'info', completed: 'success', failed: 'error',
    cancelled: 'neutral', rerunning: 'warning',
  }

  const handleCancel = async () => {
    setActing(true)
    try { await cancelAgentDomain(instanceId, stepId, domain) } catch { /* */ }
    setActing(false)
  }
  const handleRerun = async () => {
    setActing(true)
    try { await rerunAgentDomain(instanceId, stepId, domain) } catch { /* */ }
    setActing(false)
  }

  const reviewMd = info.review_md
  const thought = isRunning && liveContent ? extractLatestThought(liveContent) : null

  return (
    <div style={{ border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, overflow: 'hidden' }}>
      <div
        onClick={() => setOpen(!open)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
          cursor: 'pointer', background: 'rgba(255,255,255,0.03)',
        }}
      >
        <span>{open ? '\u25BC' : '\u25B6'}</span>
        <Badge variant={statusVariant[info.status] ?? 'neutral'} size="sm">{info.status}</Badge>
        <Badge variant="info" size="sm">{domain}</Badge>
        {isRunning && <Spinner size="sm" />}
        <span style={{ fontSize: 12, opacity: 0.6, marginLeft: 'auto' }}>{elapsedStr}</span>
        {info.pid && <span style={{ fontSize: 11, opacity: 0.4, fontFamily: 'var(--font-mono)' }}>PID {info.pid}</span>}
        <div onClick={e => e.stopPropagation()} style={{ display: 'flex', gap: 4 }}>
          {isRunning && (
            <Button variant="ghost" size="sm" onClick={handleCancel} disabled={acting}>Cancel</Button>
          )}
          {(info.status === 'failed' || info.status === 'cancelled') && (
            <Button variant="ghost" size="sm" onClick={handleRerun} disabled={acting}>Rerun</Button>
          )}
        </div>
      </div>
      {thought && (
        <div className="mx-step-content__thought-ticker">{thought}</div>
      )}
      {open && isCompleted && reviewMd && (
        <div className="mx-step-content__review-markdown">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{reviewMd}</ReactMarkdown>
        </div>
      )}
      {open && !isCompleted && liveContent && (
        <>
          <div
            onClick={() => setShowTerminal(!showTerminal)}
            style={{
              padding: '4px 12px', fontSize: 12, opacity: 0.5, cursor: 'pointer',
              userSelect: 'none',
            }}
          >
            {showTerminal ? '\u25BC Hide' : '\u25B6 Show'} full output
          </div>
          {showTerminal && (
            <pre ref={ref} className="mx-step-content__live-terminal" style={{ maxHeight: 300 }}>{liveContent}</pre>
          )}
        </>
      )}
      {open && info.error && (
        <div className="mx-step-content__error" style={{ margin: '8px 12px', fontSize: 13 }}>{info.error}</div>
      )}
    </div>
  )
}

function LiveAgentOutput({ instanceId, stepId }: { instanceId: number; stepId: string }) {
  const [output, setOutput] = useState('')
  const [showTerminal, setShowTerminal] = useState(false)
  const termRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    let active = true
    const poll = async () => {
      try {
        const text = await getStepLiveOutput(instanceId, stepId)
        if (active && text) setOutput(text)
      } catch { /* ignore */ }
    }
    poll()
    const iv = setInterval(poll, 3000)
    return () => { active = false; clearInterval(iv) }
  }, [instanceId, stepId])

  useEffect(() => {
    if (termRef.current && showTerminal) {
      termRef.current.scrollTop = termRef.current.scrollHeight
    }
  }, [output, showTerminal])

  if (!output) {
    return (
      <div className="mx-step-content__running">
        <Spinner size="sm" />
        <span>Agent is working... waiting for output</span>
      </div>
    )
  }

  const domainSections = parseDomainSections(output)

  if (domainSections.length > 1) {
    return (
      <div className="mx-step-content__live">
        <div className="mx-step-content__live-header">
          <Spinner size="sm" />
          <span>Agents working ({domainSections.length} domains)</span>
        </div>
        {domainSections.map((sec) => (
          <DomainLiveSection key={sec.domain} domain={sec.domain} content={sec.content} />
        ))}
      </div>
    )
  }

  const thought = extractLatestThought(output)

  return (
    <div className="mx-step-content__live">
      <div className="mx-step-content__live-header">
        <Spinner size="sm" />
        <span>Agent working</span>
      </div>
      <div className="mx-step-content__thought-ticker">{thought}</div>
      <div
        onClick={() => setShowTerminal(!showTerminal)}
        style={{ padding: '4px 12px', fontSize: 12, opacity: 0.5, cursor: 'pointer', userSelect: 'none' }}
      >
        {showTerminal ? '\u25BC Hide' : '\u25B6 Show'} full output
      </div>
      {showTerminal && (
        <pre ref={termRef} className="mx-step-content__live-terminal">{output}</pre>
      )}
    </div>
  )
}

function parseDomainSections(output: string): Array<{ domain: string; content: string }> {
  const sections: Array<{ domain: string; content: string }> = []
  const parts = output.split(/--- \[/)
  for (const part of parts) {
    if (!part.trim()) continue
    const closeBracket = part.indexOf('] ---')
    if (closeBracket === -1) {
      if (sections.length === 0) sections.push({ domain: 'output', content: part })
      continue
    }
    const domain = part.slice(0, closeBracket)
    const content = part.slice(closeBracket + 5).trim()
    sections.push({ domain, content })
  }
  return sections
}

function DomainLiveSection({ domain, content }: { domain: string; content: string }) {
  const [showTerminal, setShowTerminal] = useState(false)
  const ref = useRef<HTMLPreElement>(null)
  useEffect(() => {
    if (ref.current && showTerminal) {
      ref.current.scrollTop = ref.current.scrollHeight
    }
  }, [content, showTerminal])

  const thought = extractLatestThought(content)

  return (
    <div className="mx-step-content__live-domain">
      <div
        className="mx-step-content__live-domain-header"
        style={{ display: 'flex', gap: '8px', alignItems: 'center', padding: '6px 8px', background: 'rgba(255,255,255,0.05)', borderRadius: '4px', marginBottom: '4px' }}
      >
        <Badge variant="info" size="sm">{domain}</Badge>
        <Spinner size="sm" />
      </div>
      <div className="mx-step-content__thought-ticker">{thought}</div>
      <div
        onClick={() => setShowTerminal(!showTerminal)}
        style={{ padding: '4px 8px', fontSize: 12, opacity: 0.5, cursor: 'pointer', userSelect: 'none' }}
      >
        {showTerminal ? '\u25BC Hide' : '\u25B6 Show'} full output
      </div>
      {showTerminal && (
        <pre ref={ref} className="mx-step-content__live-terminal" style={{ maxHeight: '300px' }}>{content}</pre>
      )}
    </div>
  )
}

function DomainLiveFallbackCard({ domain, content }: { domain: string; content: string }) {
  const [showTerminal, setShowTerminal] = useState(false)
  const ref = useRef<HTMLPreElement>(null)
  useEffect(() => {
    if (ref.current && showTerminal) ref.current.scrollTop = ref.current.scrollHeight
  }, [content, showTerminal])

  const thought = extractLatestThought(content)

  return (
    <div style={{ border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, overflow: 'hidden' }}>
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
          background: 'rgba(255,255,255,0.03)',
        }}
      >
        <Badge variant="info" size="sm">running</Badge>
        <Badge variant="info" size="sm">{domain}</Badge>
        <Spinner size="sm" />
      </div>
      <div className="mx-step-content__thought-ticker">{thought}</div>
      <div
        onClick={() => setShowTerminal(!showTerminal)}
        style={{ padding: '4px 12px', fontSize: 12, opacity: 0.5, cursor: 'pointer', userSelect: 'none' }}
      >
        {showTerminal ? '\u25BC Hide' : '\u25B6 Show'} full output
      </div>
      {showTerminal && (
        <pre ref={ref} className="mx-step-content__live-terminal" style={{ maxHeight: 300 }}>{content}</pre>
      )}
    </div>
  )
}

const RUNNING_MESSAGES: Record<string, string> = {
  freshness_check: 'Checking PR freshness against current HEAD...',
  publish: 'Publishing review to GitHub...',
  prompt_generate: 'Building expert review prompts...',
  pr_select: 'Fetching pull requests...',
  prioritize: 'Analyzing PR priority...',
  human_gate: 'Awaiting human decision...',
}

function RunningStepIndicator({ stepType }: { stepType: string }) {
  const message = RUNNING_MESSAGES[stepType] || 'Step in progress...'
  return (
    <div className="mx-step-content__running">
      <Spinner size="sm" />
      <span>{message}</span>
    </div>
  )
}

export function StepContentViewer({ step, artifacts, instanceId }: StepContentViewerProps & { instanceId?: number }) {
  const stepArtifacts = artifacts.filter((a) => a.step_id === step.step_id)
  const Viewer = VIEWERS[step.step_type] ?? (({ content }: { content: ParsedContent }) => <DefaultView content={content} />)

  if (step.status === 'pending') {
    return <div className="mx-step-content__pending">Waiting to run...</div>
  }

  if (step.status === 'running') {
    const DOMAIN_TRACKED_TYPES = ['agent_review', 'synthesis']
    if (DOMAIN_TRACKED_TYPES.includes(step.step_type) && instanceId) {
      return <AgentDomainTracker instanceId={instanceId} stepId={step.step_id} />
    }
    const AI_STEP_TYPES = ['expert_select', 'holistic_review']
    if (AI_STEP_TYPES.includes(step.step_type) && instanceId) {
      return <LiveAgentOutput instanceId={instanceId} stepId={step.step_id} />
    }
    return <RunningStepIndicator stepType={step.step_type} />
  }

  if (step.error_message) {
    return (
      <div className="mx-step-content__error">
        <strong>Error:</strong> {step.error_message}
      </div>
    )
  }

  if (step.step_type === 'human_gate') {
    return <Viewer content={{}} step={step} instanceId={instanceId} />
  }

  if (stepArtifacts.length > 0) {
    return (
      <div className="mx-step-content">
        {stepArtifacts.map((a, i) => {
          const content = parseContent(a)
          if (!content) return <div key={i} className="mx-step-content__empty">Artifact has no content.</div>
          return <Viewer key={i} content={content} step={step} />
        })}
      </div>
    )
  }

  const outputsRaw = step.outputs_json
  if (outputsRaw) {
    let parsed: ParsedContent | null = parseOutputs(outputsRaw) as ParsedContent | null
    if (parsed) {
      const usage = parsed.usage as TokenUsage | undefined
      const WRAPPER_KEYS: Record<string, string> = {
        synthesis: 'synthesis',
        holistic_review: 'holistic',
      }
      const wrapperKey = WRAPPER_KEYS[step.step_type]
      if (wrapperKey && parsed[wrapperKey] && typeof parsed[wrapperKey] === 'object') {
        parsed = parsed[wrapperKey] as ParsedContent
      }
      return (
        <div className="mx-step-content">
          {usage && (usage.input_tokens || usage.output_tokens) && <TokenUsageBadge usage={usage} />}
          <Viewer content={parsed} step={step} />
        </div>
      )
    }
  }

  return <div className="mx-step-content__empty">No output available yet.</div>
}
