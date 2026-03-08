import { Badge } from '../common/Badge'
import { FindingCard } from './FindingCard'
import type { WorkflowArtifact } from '../../api/workflow-engine'

interface ParsedReview {
  verdict?: string
  summary?: string
  findings?: Array<Record<string, unknown>>
}

interface ReviewComparisonProps {
  artifacts: WorkflowArtifact[]
  synthesisArtifact?: WorkflowArtifact
}

function parseContent(artifact: WorkflowArtifact): ParsedReview | null {
  const raw = artifact.content_json
  if (!raw) return null
  if (typeof raw === 'string') {
    try { return JSON.parse(raw) } catch { return null }
  }
  return raw as ParsedReview
}

function ReviewColumn({ label, review }: { label: string; review: ParsedReview }) {
  const findings = review.findings ?? []
  return (
    <div className="mx-review-cmp__column">
      <div className="mx-review-cmp__column-header">
        <strong>{label}</strong>
        {review.verdict && (
          <Badge variant={review.verdict === 'APPROVE' ? 'success' : 'warning'} size="sm">
            {review.verdict}
          </Badge>
        )}
      </div>
      {review.summary && <p className="mx-review-cmp__summary">{review.summary}</p>}
      <div className="mx-review-cmp__findings">
        {findings.length === 0 && <p className="mx-review-cmp__empty">No findings.</p>}
        {findings.map((f, i) => (
          <FindingCard key={i} finding={f as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} />
        ))}
      </div>
    </div>
  )
}

export function ReviewComparison({ artifacts, synthesisArtifact }: ReviewComparisonProps) {
  const reviewArtifacts = artifacts.filter(
    (a) => a.artifact_type === 'review' || a.artifact_type === 'review_json'
  )

  if (reviewArtifacts.length < 2) {
    return <p className="mx-review-cmp__empty">Not enough review artifacts for comparison.</p>
  }

  const reviewA = parseContent(reviewArtifacts[0])
  const reviewB = parseContent(reviewArtifacts[1])

  let synthData: ParsedReview | null = null
  if (synthesisArtifact) {
    synthData = parseContent(synthesisArtifact)
  }

  const agreed = synthData ? ((synthData as Record<string, unknown>).agreed ?? []) as Array<Record<string, unknown>> : []
  const aOnly = synthData ? (((synthData as Record<string, unknown>).a_only ?? (synthData as Record<string, unknown>)['A-ONLY'] ?? []) as Array<Record<string, unknown>>) : []
  const bOnly = synthData ? (((synthData as Record<string, unknown>).b_only ?? (synthData as Record<string, unknown>)['B-ONLY'] ?? []) as Array<Record<string, unknown>>) : []

  return (
    <div className="mx-review-cmp">
      <div className="mx-review-cmp__grid">
        <ReviewColumn label="Agent A" review={reviewA ?? { findings: [] }} />
        <ReviewColumn label="Agent B" review={reviewB ?? { findings: [] }} />
      </div>

      {synthData && (agreed.length > 0 || aOnly.length > 0 || bOnly.length > 0) && (
        <div className="mx-review-cmp__synthesis-summary">
          <h5>Synthesis Classification</h5>
          <div className="mx-review-cmp__class-grid">
            {agreed.length > 0 && (
              <div className="mx-review-cmp__class-section">
                <Badge variant="success" size="sm">Agreed ({agreed.length})</Badge>
                {agreed.map((f, i) => (
                  <FindingCard key={i} finding={f as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} classification="AGREED" />
                ))}
              </div>
            )}
            {aOnly.length > 0 && (
              <div className="mx-review-cmp__class-section">
                <Badge variant="warning" size="sm">A-Only ({aOnly.length})</Badge>
                {aOnly.map((f, i) => (
                  <FindingCard key={i} finding={f as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} classification="A-ONLY" />
                ))}
              </div>
            )}
            {bOnly.length > 0 && (
              <div className="mx-review-cmp__class-section">
                <Badge variant="warning" size="sm">B-Only ({bOnly.length})</Badge>
                {bOnly.map((f, i) => (
                  <FindingCard key={i} finding={f as Record<string, unknown> & { title?: string; severity?: string; location?: { file?: string; start_line?: number; end_line?: number; raw?: string }; problem?: string; fix?: string }} classification="B-ONLY" />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
