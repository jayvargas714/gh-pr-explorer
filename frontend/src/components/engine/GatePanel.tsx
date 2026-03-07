import { useState } from 'react'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import { Modal } from '../common/Modal'
import { useWorkflowEngineStore } from '../../stores/useWorkflowEngineStore'
import type { WorkflowInstance } from '../../api/workflow-engine'

interface GatePanelProps {
  instance: WorkflowInstance
  onClose: () => void
}

export function GatePanel({ instance, onClose }: GatePanelProps) {
  const { approveGate, rejectGate, loading } = useWorkflowEngineStore()
  const [editMode, setEditMode] = useState(false)
  const [editNotes, setEditNotes] = useState('')

  const gateStep = instance.steps?.find(s => s.status === 'awaiting_gate')
  if (!gateStep) return null

  const gatePayload = tryParseOutputs(gateStep as unknown as Record<string, unknown>)
  const synthesis = gatePayload?.synthesis as Record<string, unknown> | undefined
  const freshness = (gatePayload?.freshness ?? []) as FreshnessItem[]

  const handleApprove = async () => {
    const data: Record<string, unknown> = { gate_decision: 'approve' }
    if (editNotes.trim()) {
      data.notes = editNotes.trim()
    }
    await approveGate(instance.id, data)
    onClose()
  }

  const handleReject = async () => {
    await rejectGate(instance.id)
    onClose()
  }

  return (
    <Modal isOpen onClose={onClose} title="Human Review Gate" size="lg">
      <div className="mx-gate">
        {synthesis && <SynthesisSummary synthesis={synthesis as Record<string, unknown>} />}

        {freshness.length > 0 && (
          <div className="mx-gate__freshness">
            <h4>Freshness</h4>
            <div className="mx-gate__freshness-list">
              {freshness.map((f: FreshnessItem, idx: number) => (
                <FreshnessBadge key={idx} item={f} />
              ))}
            </div>
          </div>
        )}

        {!editMode ? (
          <div className="mx-gate__actions">
            <Button variant="primary" onClick={handleApprove} disabled={loading}>
              {loading ? <Spinner size="sm" /> : 'Approve & Publish'}
            </Button>
            <Button variant="ghost" onClick={() => setEditMode(true)} disabled={loading}>
              Edit & Approve
            </Button>
            <Button variant="danger" onClick={handleReject} disabled={loading}>
              Reject
            </Button>
          </div>
        ) : (
          <div className="mx-gate__edit">
            <h4>Notes / Edits</h4>
            <textarea
              className="mx-input mx-gate__textarea"
              placeholder="Add notes or edits before approving..."
              value={editNotes}
              onChange={(e) => setEditNotes(e.target.value)}
              rows={4}
            />
            <div className="mx-gate__actions">
              <Button variant="primary" onClick={handleApprove} disabled={loading}>
                {loading ? <Spinner size="sm" /> : 'Submit & Approve'}
              </Button>
              <Button variant="ghost" onClick={() => setEditMode(false)}>
                Cancel Edit
              </Button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  )
}

interface FreshnessItem {
  pr_number: number
  classification: string
  review_sha?: string
  current_sha?: string
}

const FRESHNESS_VARIANTS: Record<string, 'success' | 'error' | 'warning' | 'neutral'> = {
  CURRENT: 'success',
  'STALE-MINOR': 'warning',
  'STALE-MAJOR': 'error',
  UNKNOWN: 'neutral',
}

function FreshnessBadge({ item }: { item: FreshnessItem }) {
  return (
    <div className="mx-gate__freshness-item">
      <span>PR #{item.pr_number}</span>
      <Badge variant={FRESHNESS_VARIANTS[item.classification] ?? 'neutral'} size="sm">
        {item.classification}
      </Badge>
    </div>
  )
}

function SynthesisSummary({ synthesis }: { synthesis: Record<string, unknown> }) {
  const verdict = synthesis.verdict as string
  const agreed = (synthesis.agreed as unknown[]) ?? []
  const aOnly = (synthesis.a_only as unknown[]) ?? []
  const bOnly = (synthesis.b_only as unknown[]) ?? []
  const totalFindings = (synthesis.total_findings as number) ?? 0
  const agentA = (synthesis.agent_a as string) ?? 'Agent A'
  const agentB = (synthesis.agent_b as string) ?? 'Agent B'

  const verdictVariant: Record<string, 'success' | 'error' | 'warning'> = {
    APPROVE: 'success',
    CHANGES_REQUESTED: 'error',
    COMMENT: 'warning',
  }

  return (
    <div className="mx-gate__synthesis">
      <div className="mx-gate__synthesis-header">
        <h4>Synthesis</h4>
        <Badge variant={verdictVariant[verdict] ?? 'warning'} size="md">
          {verdict}
        </Badge>
      </div>

      <div className="mx-gate__synthesis-stats">
        <div className="mx-gate__stat">
          <span className="mx-gate__stat-value">{totalFindings}</span>
          <span className="mx-gate__stat-label">Total Findings</span>
        </div>
        <div className="mx-gate__stat">
          <span className="mx-gate__stat-value mx-gate__stat-value--agreed">{agreed.length}</span>
          <span className="mx-gate__stat-label">Agreed</span>
        </div>
        <div className="mx-gate__stat">
          <span className="mx-gate__stat-value mx-gate__stat-value--disputed">
            {aOnly.length + bOnly.length}
          </span>
          <span className="mx-gate__stat-label">Disputed</span>
        </div>
      </div>

      {agreed.length > 0 && (
        <FindingsSection title="Agreed" items={agreed} classification="AGREED" />
      )}
      {aOnly.length > 0 && (
        <FindingsSection title={`${agentA} Only`} items={aOnly} classification="A-ONLY" />
      )}
      {bOnly.length > 0 && (
        <FindingsSection title={`${agentB} Only`} items={bOnly} classification="B-ONLY" />
      )}
    </div>
  )
}

function FindingsSection({
  title,
  items,
  classification,
}: {
  title: string
  items: unknown[]
  classification: string
}) {
  const classVariant = classification === 'AGREED' ? 'success' : 'warning'

  return (
    <div className="mx-gate__findings-section">
      <h5>
        {title}
        <Badge variant={classVariant} size="sm" className="mx-gate__findings-count">
          {items.length}
        </Badge>
      </h5>
      <ul className="mx-gate__findings-list">
        {items.slice(0, 10).map((item, idx) => {
          const finding = (item as Record<string, unknown>)
          const f = (finding.finding_a ?? finding.finding ?? {}) as Record<string, unknown>
          return (
            <li key={idx} className="mx-gate__finding">
              <Badge
                variant={
                  f.severity === 'critical' ? 'error' : f.severity === 'major' ? 'warning' : 'neutral'
                }
                size="sm"
              >
                {(f.severity as string) ?? 'minor'}
              </Badge>
              <span>{(f.title as string) ?? 'Untitled finding'}</span>
            </li>
          )
        })}
        {items.length > 10 && (
          <li className="mx-gate__finding mx-gate__finding--more">
            ...and {items.length - 10} more
          </li>
        )}
      </ul>
    </div>
  )
}

function tryParseOutputs(step: Record<string, unknown>): Record<string, unknown> | null {
  try {
    const raw = step.outputs_json
    if (typeof raw === 'string') return JSON.parse(raw)
    if (typeof raw === 'object' && raw !== null) return raw as Record<string, unknown>
  } catch { /* ignore */ }
  return null
}
