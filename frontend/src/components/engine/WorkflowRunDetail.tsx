import { useEffect } from 'react'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { Spinner } from '../common/Spinner'
import { Card } from '../common/Card'
import { useWorkflowEngineStore } from '../../stores/useWorkflowEngineStore'
import type { WorkflowStep, WorkflowInstance } from '../../api/workflow-engine'

const STEP_STATUS_COLOR: Record<string, string> = {
  completed: 'var(--mx-color-success)',
  running: 'var(--mx-color-info)',
  pending: 'var(--mx-color-text-muted)',
  awaiting_gate: 'var(--mx-color-warning)',
  failed: 'var(--mx-color-error)',
}

const STEP_STATUS_VARIANT: Record<string, 'success' | 'error' | 'warning' | 'info' | 'neutral'> = {
  completed: 'success',
  running: 'info',
  pending: 'neutral',
  awaiting_gate: 'warning',
  failed: 'error',
}

const STEP_TYPE_LABELS: Record<string, string> = {
  pr_select: 'PR Select',
  prioritize: 'Prioritize',
  prompt_generate: 'Prompt Gen',
  agent_review: 'Agent Review',
  synthesis: 'Synthesis',
  freshness_check: 'Freshness',
  human_gate: 'Human Gate',
  publish: 'Publish',
  expert_select: 'Expert Select',
  holistic_review: 'Holistic Review',
}

function formatStepType(type: string): string {
  return STEP_TYPE_LABELS[type] ?? type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function formatStatus(status: string): string {
  return status.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

interface WorkflowRunDetailProps {
  instance: WorkflowInstance
  onBack: () => void
  onOpenGate: () => void
}

export function WorkflowRunDetail({ instance, onBack, onOpenGate }: WorkflowRunDetailProps) {
  const { selectedInstance, fetchInstance, loading } = useWorkflowEngineStore()

  useEffect(() => {
    fetchInstance(instance.id)
  }, [instance.id, fetchInstance])

  useEffect(() => {
    if (!selectedInstance || selectedInstance.status === 'completed' || selectedInstance.status === 'failed' || selectedInstance.status === 'cancelled') {
      return
    }
    const interval = setInterval(() => {
      fetchInstance(instance.id)
    }, 3000)
    return () => clearInterval(interval)
  }, [instance.id, selectedInstance?.status, fetchInstance])

  const steps: WorkflowStep[] = selectedInstance?.steps ?? []

  const completedCount = steps.filter(s => s.status === 'completed').length
  const totalCount = steps.length
  const progressPct = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0

  return (
    <div className="mx-engine-detail">
      <div className="mx-engine-detail__header">
        <Button variant="ghost" size="sm" onClick={onBack}>
          &larr; Back to Runs
        </Button>
        <div className="mx-engine-detail__title">
          <h3>Run #{instance.id}</h3>
          <Badge variant={STEP_STATUS_VARIANT[selectedInstance?.status ?? instance.status] ?? 'neutral'}>
            {formatStatus(selectedInstance?.status ?? instance.status)}
          </Badge>
        </div>
        <span className="mx-engine-detail__template">
          {instance.template_name || `Template #${instance.template_id}`}
        </span>
      </div>

      <div className="mx-engine-detail__progress">
        <div className="mx-engine-detail__progress-label">
          <span>Progress</span>
          <span>{completedCount}/{totalCount} steps ({progressPct}%)</span>
        </div>
        <div className="mx-progress__track">
          <div
            className="mx-progress__bar"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {loading && steps.length === 0 ? (
        <div className="mx-engine-detail__loading">
          <Spinner />
        </div>
      ) : (
        <div className="mx-engine-pipeline">
          {steps.map((step, idx) => (
            <div key={step.step_id} className="mx-engine-pipeline__node-group">
              {idx > 0 && <div className="mx-engine-pipeline__edge" />}
              <StepNode step={step} onOpenGate={onOpenGate} />
            </div>
          ))}
        </div>
      )}

      {selectedInstance?.artifacts && selectedInstance.artifacts.length > 0 && (
        <Card className="mx-engine-detail__artifacts">
          <h4>Artifacts</h4>
          <div className="mx-engine-detail__artifact-list">
            {selectedInstance.artifacts.map((a) => (
              <div key={a.id} className="mx-engine-detail__artifact">
                <Badge variant="info" size="sm">{a.artifact_type}</Badge>
                {a.pr_number && <span className="mx-engine-detail__artifact-pr">PR #{a.pr_number}</span>}
                <span className="mx-engine-detail__artifact-step">{a.step_id}</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

function StepNode({ step, onOpenGate }: { step: WorkflowStep; onOpenGate: () => void }) {
  const color = STEP_STATUS_COLOR[step.status] ?? 'var(--mx-color-text-muted)'
  const isGate = step.step_type === 'human_gate' && step.status === 'awaiting_gate'
  const isRunning = step.status === 'running'

  return (
    <div
      className={`mx-engine-pipeline__node ${isGate ? 'mx-engine-pipeline__node--gate' : ''}`}
      style={{ borderColor: color }}
    >
      <div className="mx-engine-pipeline__node-indicator" style={{ backgroundColor: color }}>
        {isRunning && <span className="mx-engine-pipeline__pulse" />}
      </div>
      <div className="mx-engine-pipeline__node-body">
        <span className="mx-engine-pipeline__node-type">{formatStepType(step.step_type)}</span>
        <span className="mx-engine-pipeline__node-id">{step.step_id}</span>
        <Badge variant={STEP_STATUS_VARIANT[step.status] ?? 'neutral'} size="sm">
          {formatStatus(step.status)}
        </Badge>
        {step.error_message && (
          <span className="mx-engine-pipeline__node-error" title={step.error_message}>
            {step.error_message.slice(0, 60)}
            {step.error_message.length > 60 ? '...' : ''}
          </span>
        )}
      </div>
      {isGate && (
        <Button variant="primary" size="sm" onClick={onOpenGate}>
          Review Gate
        </Button>
      )}
    </div>
  )
}
