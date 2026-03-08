import { useEffect, useRef, useState } from 'react'
import { Badge } from '../common/Badge'
import { Spinner } from '../common/Spinner'
import { FindingCard } from './FindingCard'
import { getStepLiveOutput } from '../../api/workflow-engine'
import type { WorkflowStep, WorkflowArtifact } from '../../api/workflow-engine'

interface StepContentViewerProps {
  step: WorkflowStep
  artifacts: WorkflowArtifact[]
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

function PRSelectView({ content }: { content: ParsedContent }) {
  const prs = (content.prs ?? content.selected ?? []) as Array<{
    number: number; title?: string; url?: string; author?: string
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
          {pr.author && <span className="mx-step-content__pr-author">@{pr.author}</span>}
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

function SynthesisView({ content }: { content: ParsedContent }) {
  const verdict = content.verdict as string | undefined
  const agreed = (content.agreed ?? []) as Array<Record<string, unknown>>
  const aOnly = ((content.a_only ?? content['A-ONLY'] ?? []) as Array<Record<string, unknown>>)
  const bOnly = ((content.b_only ?? content['B-ONLY'] ?? []) as Array<Record<string, unknown>>)
  const summary = content.summary as string | undefined

  return (
    <div className="mx-step-content__synthesis">
      {verdict && (
        <div className="mx-step-content__verdict">
          <strong>Final Verdict:</strong>
          <Badge variant={verdict === 'APPROVE' ? 'success' : 'warning'}>{verdict}</Badge>
        </div>
      )}
      {summary && <p className="mx-step-content__summary">{summary}</p>}
      <div className="mx-step-content__classification-grid">
        <Section label="Agreed" variant="success" items={agreed} classification="AGREED" />
        <Section label="Agent A Only" variant="warning" items={aOnly} classification="A-ONLY" />
        <Section label="Agent B Only" variant="warning" items={bOnly} classification="B-ONLY" />
      </div>
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
    pr_number?: number; status?: string; head_sha?: string; reviewed_sha?: string
  }>
  if (!checks.length) return <p className="mx-step-content__empty">No freshness data.</p>

  return (
    <div className="mx-step-content__freshness">
      {checks.map((c, i) => (
        <div key={i} className="mx-step-content__freshness-item">
          <span className="mx-step-content__freshness-pr">#{c.pr_number}</span>
          <Badge
            variant={c.status === 'CURRENT' ? 'success' : c.status === 'STALE-MINOR' ? 'warning' : 'error'}
            size="sm"
          >
            {c.status ?? 'UNKNOWN'}
          </Badge>
          {c.head_sha && <code className="mx-step-content__sha">{c.head_sha.slice(0, 8)}</code>}
        </div>
      ))}
    </div>
  )
}

function HumanGateView({ step }: { step: WorkflowStep }) {
  const statusLabel = step.status === 'awaiting_gate' ? 'Awaiting human decision' : step.status
  return (
    <div className="mx-step-content__gate">
      <Badge variant={step.status === 'awaiting_gate' ? 'warning' : step.status === 'completed' ? 'success' : 'neutral'}>
        {statusLabel}
      </Badge>
      {step.status === 'completed' && <p>Gate has been resolved.</p>}
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
  const blocking = (content.blocking ?? []) as Array<Record<string, unknown>>
  const nonBlocking = (content.non_blocking ?? []) as Array<Record<string, unknown>>
  const recs = (content.recommendations ?? []) as Array<{ priority?: string; text?: string }>
  return (
    <div className="mx-step-content__holistic">
      {verdict && (
        <div className="mx-step-content__verdict">
          <strong>Verdict:</strong>
          <Badge variant={verdict === 'APPROVE' ? 'success' : verdict === 'CHANGES_REQUESTED' ? 'error' : 'warning'}>
            {verdict}
          </Badge>
          {confidence && <Badge variant="neutral" size="sm">{confidence} confidence</Badge>}
        </div>
      )}
      {summary && <p className="mx-step-content__summary">{summary}</p>}
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

const VIEWERS: Record<string, React.FC<{ content: ParsedContent; step: WorkflowStep }>> = {
  pr_select: ({ content }) => <PRSelectView content={content} />,
  prioritize: ({ content }) => <PrioritizeView content={content} />,
  prompt_generate: ({ content }) => <PromptView content={content} />,
  agent_review: ({ content }) => <ReviewView content={content} />,
  synthesis: ({ content }) => <SynthesisView content={content} />,
  freshness_check: ({ content }) => <FreshnessView content={content} />,
  human_gate: ({ step }) => <HumanGateView step={step} />,
  publish: ({ content }) => <DefaultView content={content} />,
  expert_select: ({ content }) => <ExpertSelectView content={content} />,
  holistic_review: ({ content }) => <HolisticView content={content} />,
  followup_check: ({ content }) => <FollowupCheckView content={content} />,
  followup_action: ({ content }) => <FollowupActionView content={content} />,
}

function LiveAgentOutput({ instanceId, stepId }: { instanceId: number; stepId: string }) {
  const [output, setOutput] = useState('')
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
    if (termRef.current) {
      termRef.current.scrollTop = termRef.current.scrollHeight
    }
  }, [output])

  if (!output) {
    return (
      <div className="mx-step-content__running">
        <Spinner size="sm" />
        <span>Agent is working... waiting for output</span>
      </div>
    )
  }

  return (
    <div className="mx-step-content__live">
      <div className="mx-step-content__live-header">
        <Spinner size="sm" />
        <span>Agent output (live)</span>
      </div>
      <pre ref={termRef} className="mx-step-content__live-terminal">{output}</pre>
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
    if (step.step_type === 'agent_review' && instanceId) {
      return <LiveAgentOutput instanceId={instanceId} stepId={step.step_id} />
    }
    return <div className="mx-step-content__running"><Spinner size="sm" /> Step in progress...</div>
  }

  if (step.error_message) {
    return (
      <div className="mx-step-content__error">
        <strong>Error:</strong> {step.error_message}
      </div>
    )
  }

  if (step.step_type === 'human_gate') {
    return <Viewer content={{}} step={step} />
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
    let parsed: ParsedContent | null = null
    if (typeof outputsRaw === 'string') {
      try { parsed = JSON.parse(outputsRaw) } catch { parsed = null }
    }
    if (parsed) {
      return (
        <div className="mx-step-content">
          <Viewer content={parsed} step={step} />
        </div>
      )
    }
  }

  return <div className="mx-step-content__empty">No output available yet.</div>
}
